# pylint: disable=too-many-arguments
"""Helper code for client.py and async_client.py."""
from __future__ import annotations

from typing import TYPE_CHECKING, List, NamedTuple, Optional, Tuple, Type, Union

import solders.system_program as sp
from solana.rpc.api import Client
from solana.rpc.commitment import Commitment
from solana.rpc.types import TokenAccountOpts, TxOpts
from solana.transaction import Transaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.rpc.responses import GetAccountInfoResp

import spl.token.instructions as spl_token
from spl.token._layouts import ACCOUNT_LAYOUT, MINT_LAYOUT, MULTISIG_LAYOUT  # type: ignore
from spl.token.constants import WRAPPED_SOL_MINT

if TYPE_CHECKING:
    from spl.token.client import Token


class AccountInfo(NamedTuple):
    """Information about an account."""

    mint: Pubkey
    """The mint associated with this account."""
    owner: Pubkey
    """Owner of this account."""
    amount: int
    """Amount of tokens this account holds."""
    delegate: Optional[Pubkey]
    """The delegate for this account."""
    delegated_amount: int
    """The amount of tokens the delegate authorized to the delegate."""
    is_initialized: bool
    """ Is this account initialized."""
    is_frozen: bool
    """Is this account frozen."""
    is_native: bool
    """Is this a native token account."""
    rent_exempt_reserve: Optional[int]
    """If this account is a native token, it must be rent-exempt.

    This value logs the rent-exempt reserve which must remain in the balance
    until the account is closed.
    """
    close_authority: Optional[Pubkey]
    """Optional authority to close the account."""


class MintInfo(NamedTuple):
    """Information about the mint."""

    mint_authority: Optional[Pubkey]
    """"Optional authority used to mint new tokens.

    The mint authority may only be provided during mint creation. If no mint
    authority is present then the mint has a fixed supply and no further tokens
    may be minted.
    """
    supply: int
    """Total supply of tokens."""
    decimals: int
    """Number of base 10 digits to the right of the decimal place."""
    is_initialized: bool
    """Is this mint initialized."""
    freeze_authority: Optional[Pubkey]
    """ Optional authority to freeze token accounts."""


class _TokenCore:  # pylint: disable=too-few-public-methods

    pubkey: Pubkey
    """The public key identifying this mint."""

    program_id: Pubkey
    """Program Identifier for the Token program."""

    payer: Keypair
    """Fee payer."""

    def __init__(self, pubkey: Pubkey, program_id: Pubkey, payer: Keypair) -> None:
        """Initialize a client to a SPL-Token program."""
        self.pubkey, self.program_id, self.payer = pubkey, program_id, payer

    def _get_accounts_args(
        self,
        owner: Pubkey,
        commitment: Optional[Commitment],
        encoding,
        default_commitment: Commitment,
    ) -> Tuple[Pubkey, TokenAccountOpts, Commitment]:
        commitment_to_use = default_commitment if commitment is None else commitment
        return (
            owner,
            TokenAccountOpts(mint=self.pubkey, encoding=encoding),
            commitment_to_use,
        )

    @staticmethod
    def _create_mint_args(
        conn: Client,
        payer: Keypair,
        mint_authority: Pubkey,
        decimals: int,
        program_id: Pubkey,
        freeze_authority: Optional[Pubkey],
        skip_confirmation: bool,
        balance_needed: int,
        cls: Type[Token],
        commitment: Commitment,
    ) -> Tuple[Token, Transaction, Keypair, Keypair, TxOpts]:
        mint_keypair = Keypair()
        token = cls(conn, mint_keypair.pubkey(), program_id, payer)  # type: ignore
        # Construct transaction
        txn = Transaction(fee_payer=payer.pubkey())
        txn.add(
            sp.create_account(
                sp.CreateAccountParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=mint_keypair.pubkey(),
                    lamports=balance_needed,
                    space=MINT_LAYOUT.sizeof(),
                    owner=program_id,
                )
            )
        )
        txn.add(
            spl_token.initialize_mint(
                spl_token.InitializeMintParams(
                    program_id=program_id,
                    mint=mint_keypair.pubkey(),
                    decimals=decimals,
                    mint_authority=mint_authority,
                    freeze_authority=freeze_authority,
                )
            )
        )
        return (
            token,
            txn,
            payer,
            mint_keypair,
            TxOpts(skip_confirmation=skip_confirmation, preflight_commitment=commitment),
        )

    def _create_account_args(
        self,
        owner: Pubkey,
        skip_confirmation: bool,
        balance_needed: int,
        commitment: Commitment,
    ) -> Tuple[Pubkey, Transaction, Keypair, Keypair, TxOpts]:
        new_keypair = Keypair()
        # Allocate memory for the account

        # Construct transaction
        txn = Transaction(fee_payer=self.payer.pubkey())
        txn.add(
            sp.create_account(
                sp.CreateAccountParams(
                    from_pubkey=self.payer.pubkey(),
                    to_pubkey=new_keypair.pubkey(),
                    lamports=balance_needed,
                    space=ACCOUNT_LAYOUT.sizeof(),
                    owner=self.program_id,
                )
            )
        )
        txn.add(
            spl_token.initialize_account(
                spl_token.InitializeAccountParams(
                    account=new_keypair.pubkey(),
                    mint=self.pubkey,
                    owner=owner,
                    program_id=self.program_id,
                )
            )
        )
        return (
            new_keypair.pubkey(),
            txn,
            self.payer,
            new_keypair,
            TxOpts(skip_confirmation=skip_confirmation, preflight_commitment=commitment),
        )

    def _create_associated_token_account_args(
        self,
        owner: Pubkey,
        skip_confirmation: bool,
        commitment: Commitment,
    ) -> Tuple[Pubkey, Transaction, Keypair, TxOpts]:

        # Construct transaction
        txn = Transaction(fee_payer=self.payer.pubkey())
        create_txn = spl_token.create_associated_token_account(payer=self.payer.pubkey(), owner=owner, mint=self.pubkey)
        txn.add(create_txn)
        return (
            create_txn.accounts[1].pubkey,
            txn,
            self.payer,
            TxOpts(skip_confirmation=skip_confirmation, preflight_commitment=commitment),
        )

    @staticmethod
    def _create_wrapped_native_account_args(
        program_id: Pubkey,
        owner: Pubkey,
        payer: Keypair,
        amount: int,
        skip_confirmation: bool,
        balance_needed: int,
        commitment: Commitment,
    ) -> Tuple[Pubkey, Transaction, Keypair, Keypair, TxOpts]:
        new_keypair = Keypair()
        # Allocate memory for the account
        # Construct transaction
        txn = Transaction(fee_payer=payer.pubkey())
        txn.add(
            sp.create_account(
                sp.CreateAccountParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=new_keypair.pubkey(),
                    lamports=balance_needed,
                    space=ACCOUNT_LAYOUT.sizeof(),
                    owner=program_id,
                )
            )
        )

        txn.add(
            sp.transfer(
                sp.TransferParams(
                    from_pubkey=payer.pubkey(),
                    to_pubkey=new_keypair.pubkey(),
                    lamports=amount,
                )
            )
        )

        txn.add(
            spl_token.initialize_account(
                spl_token.InitializeAccountParams(
                    account=new_keypair.pubkey(),
                    mint=WRAPPED_SOL_MINT,
                    owner=owner,
                    program_id=program_id,
                )
            )
        )

        return (
            new_keypair.pubkey(),
            txn,
            payer,
            new_keypair,
            TxOpts(skip_confirmation=skip_confirmation, preflight_commitment=commitment),
        )

    def _transfer_args(
        self,
        source: Pubkey,
        dest: Pubkey,
        owner: Union[Keypair, Pubkey],
        amount: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.transfer(
                spl_token.TransferParams(
                    program_id=self.program_id,
                    source=source,
                    dest=dest,
                    owner=owner_pubkey,
                    amount=amount,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _set_authority_args(
        self,
        account: Pubkey,
        current_authority: Union[Keypair, Pubkey],
        authority_type: spl_token.AuthorityType,
        new_authority: Optional[Pubkey],
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, Keypair, List[Keypair], TxOpts]:
        if isinstance(current_authority, Keypair):
            current_authority_pubkey = current_authority.pubkey()
            signers = [current_authority]
        else:
            current_authority_pubkey = current_authority
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.set_authority(
                spl_token.SetAuthorityParams(
                    program_id=self.program_id,
                    account=account,
                    authority=authority_type,
                    current_authority=current_authority_pubkey,
                    signers=[signer.pubkey() for signer in signers],
                    new_authority=new_authority,
                )
            )
        )

        return txn, self.payer, signers, opts

    def _mint_to_args(
        self,
        dest: Pubkey,
        mint_authority: Union[Keypair, Pubkey],
        amount: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(mint_authority, Keypair):
            owner_pubkey = mint_authority.pubkey()
            signers = [mint_authority]
        else:
            owner_pubkey = mint_authority
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.mint_to(
                spl_token.MintToParams(
                    program_id=self.program_id,
                    mint=self.pubkey,
                    dest=dest,
                    mint_authority=owner_pubkey,
                    amount=amount,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _create_mint_info(self, info: GetAccountInfoResp) -> MintInfo:
        value = info.value
        if value is None:
            raise ValueError("Failed to find mint account")
        owner = value.owner
        if owner != self.program_id:
            raise AttributeError(f"Invalid mint owner: {owner}")

        bytes_data = value.data
        if len(bytes_data) != MINT_LAYOUT.sizeof():
            raise ValueError("Invalid mint size")

        decoded_data = MINT_LAYOUT.parse(bytes_data)
        decimals = decoded_data.decimals

        mint_authority = None if decoded_data.mint_authority_option == 0 else Pubkey(decoded_data.mint_authority)

        supply = decoded_data.supply
        is_initialized = decoded_data.is_initialized != 0

        freeze_authority = None if decoded_data.freeze_authority_option == 0 else Pubkey(decoded_data.freeze_authority)

        return MintInfo(mint_authority, supply, decimals, is_initialized, freeze_authority)

    def _create_account_info(self, info: GetAccountInfoResp) -> AccountInfo:
        value = info.value
        if value is None:
            raise ValueError("Invalid account owner")
        if value.owner != self.program_id:
            raise AttributeError("Invalid account owner")

        bytes_data = value.data
        if len(bytes_data) != ACCOUNT_LAYOUT.sizeof():
            raise ValueError("Invalid account size")

        decoded_data = ACCOUNT_LAYOUT.parse(bytes_data)

        mint = Pubkey(decoded_data.mint)
        owner = Pubkey(decoded_data.owner)
        amount = decoded_data.amount

        if decoded_data.delegate_option == 0:
            delegate = None
            delegated_amount = 0
        else:
            delegate = Pubkey(decoded_data.delegate)
            delegated_amount = decoded_data.delegated_amount

        is_initialized = decoded_data.state != 0
        is_frozen = decoded_data.state == 2

        if decoded_data.is_native_option == 1:
            rent_exempt_reserve = decoded_data.is_native
            is_native = True
        else:
            rent_exempt_reserve = None
            is_native = False

        close_authority = None if decoded_data.close_authority_option == 0 else Pubkey(decoded_data.owner)

        if mint != self.pubkey:
            raise AttributeError(f"Invalid account mint: {decoded_data.mint} != {self.pubkey}")

        return AccountInfo(
            mint,
            owner,
            amount,
            delegate,
            delegated_amount,
            is_initialized,
            is_frozen,
            is_native,
            rent_exempt_reserve,
            close_authority,
        )

    def _approve_args(
        self,
        source: Pubkey,
        delegate: Pubkey,
        owner: Union[Keypair, Pubkey],
        amount: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, Keypair, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.approve(
                spl_token.ApproveParams(
                    program_id=self.program_id,
                    source=source,
                    delegate=delegate,
                    owner=owner_pubkey,
                    amount=amount,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, self.payer, signers, opts

    def _revoke_args(
        self,
        account: Pubkey,
        owner: Union[Keypair, Pubkey],
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, Keypair, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.revoke(
                spl_token.RevokeParams(
                    program_id=self.program_id,
                    account=account,
                    owner=owner_pubkey,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, self.payer, signers, opts

    def _freeze_account_args(
        self,
        account: Pubkey,
        authority: Union[Pubkey, Keypair],
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(authority, Keypair):
            authority_pubkey = authority.pubkey()
            base_signers = [authority]
        else:
            authority_pubkey = authority
            base_signers = multi_signers if multi_signers else []
        fee_payer_keypair = self.payer
        txn = Transaction(fee_payer=fee_payer_keypair.pubkey()).add(
            spl_token.freeze_account(
                spl_token.FreezeAccountParams(
                    program_id=self.program_id,
                    account=account,
                    mint=self.pubkey,
                    authority=authority_pubkey,
                    multi_signers=[signer.pubkey() for signer in base_signers],
                )
            )
        )
        signers = list(set(base_signers) | {fee_payer_keypair})
        return txn, signers, opts

    def _thaw_account_args(
        self,
        account: Pubkey,
        authority: Union[Pubkey, Keypair],
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(authority, Keypair):
            authority_pubkey = authority.pubkey()
            base_signers = [authority]
        else:
            authority_pubkey = authority
            base_signers = multi_signers if multi_signers else []
        fee_payer_keypair = self.payer
        txn = Transaction(fee_payer=fee_payer_keypair.pubkey()).add(
            spl_token.thaw_account(
                spl_token.ThawAccountParams(
                    program_id=self.program_id,
                    account=account,
                    mint=self.pubkey,
                    authority=authority_pubkey,
                    multi_signers=[signer.pubkey() for signer in base_signers],
                )
            )
        )
        signers = list(set(base_signers) | {fee_payer_keypair})
        return txn, signers, opts

    def _close_account_args(
        self,
        account: Pubkey,
        dest: Pubkey,
        authority: Union[Pubkey, Keypair],
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(authority, Keypair):
            authority_pubkey = authority.pubkey()
            signers = [authority]
        else:
            authority_pubkey = authority
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.close_account(
                spl_token.CloseAccountParams(
                    program_id=self.program_id,
                    account=account,
                    dest=dest,
                    owner=authority_pubkey,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _burn_args(
        self,
        account: Pubkey,
        owner: Union[Pubkey, Keypair],
        amount: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.burn(
                spl_token.BurnParams(
                    program_id=self.program_id,
                    account=account,
                    mint=self.pubkey,
                    owner=owner_pubkey,
                    amount=amount,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _create_multisig_args(
        self,
        m: int,
        signers: List[Pubkey],
        balance_needed: int,
    ) -> Tuple[Transaction, Keypair, Keypair]:
        multisig_keypair = Keypair()

        txn = Transaction(fee_payer=self.payer.pubkey())
        txn.add(
            sp.create_account(
                sp.CreateAccountParams(
                    from_pubkey=self.payer.pubkey(),
                    to_pubkey=multisig_keypair.pubkey(),
                    lamports=balance_needed,
                    space=MULTISIG_LAYOUT.sizeof(),
                    owner=self.program_id,
                )
            )
        )
        txn.add(
            spl_token.initialize_multisig(
                spl_token.InitializeMultisigParams(
                    program_id=self.program_id,
                    multisig=multisig_keypair.pubkey(),
                    m=m,
                    signers=signers,
                )
            )
        )

        return txn, self.payer, multisig_keypair

    def _transfer_checked_args(
        self,
        source: Pubkey,
        dest: Pubkey,
        owner: Union[Keypair, Pubkey],
        amount: int,
        decimals: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.transfer_checked(
                spl_token.TransferCheckedParams(
                    program_id=self.program_id,
                    source=source,
                    mint=self.pubkey,
                    dest=dest,
                    owner=owner_pubkey,
                    amount=amount,
                    decimals=decimals,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _mint_to_checked_args(
        self,
        dest: Pubkey,
        mint_authority: Union[Keypair, Pubkey],
        amount: int,
        decimals: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(mint_authority, Keypair):
            owner_pubkey = mint_authority.pubkey()
            signers = [mint_authority]
        else:
            owner_pubkey = mint_authority
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.mint_to_checked(
                spl_token.MintToCheckedParams(
                    program_id=self.program_id,
                    mint=self.pubkey,
                    dest=dest,
                    mint_authority=owner_pubkey,
                    amount=amount,
                    decimals=decimals,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _burn_checked_args(
        self,
        account: Pubkey,
        owner: Union[Keypair, Pubkey],
        amount: int,
        decimals: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.burn_checked(
                spl_token.BurnCheckedParams(
                    program_id=self.program_id,
                    mint=self.pubkey,
                    account=account,
                    owner=owner_pubkey,
                    amount=amount,
                    decimals=decimals,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, signers, opts

    def _approve_checked_args(
        self,
        source: Pubkey,
        delegate: Pubkey,
        owner: Union[Keypair, Pubkey],
        amount: int,
        decimals: int,
        multi_signers: Optional[List[Keypair]],
        opts: TxOpts,
    ) -> Tuple[Transaction, Keypair, List[Keypair], TxOpts]:
        if isinstance(owner, Keypair):
            owner_pubkey = owner.pubkey()
            signers = [owner]
        else:
            owner_pubkey = owner
            signers = multi_signers if multi_signers else []

        txn = Transaction(fee_payer=self.payer.pubkey()).add(
            spl_token.approve_checked(
                spl_token.ApproveCheckedParams(
                    program_id=self.program_id,
                    source=source,
                    mint=self.pubkey,
                    delegate=delegate,
                    owner=owner_pubkey,
                    amount=amount,
                    decimals=decimals,
                    signers=[signer.pubkey() for signer in signers],
                )
            )
        )
        return txn, self.payer, signers, opts
