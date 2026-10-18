"""Payment-rail adapters: INERT by design.

======================================================================
HONEST BOUNDARY — READ THIS FIRST
======================================================================
This module contains INERT payment-rail adapters for CIPS, e-CNY, and
mBridge. They are FORM GENERATION / REFERENCE code only:

* Nothing in this module moves money, holds credentials, or calls any
  live system.
* Every adapter method that would touch a payment rail RAISES instead of
  acting: ``ProductionGatedError`` while ``config.RAILS_PRODUCTION`` is
  disabled, and ``NotImplementedError`` even when it is enabled (the
  licensed integration does not exist in this prototype).
* ``build_pain001`` generates an ISO 20022 message TEXT. The text is not
  transmitted, signed, or settled; generating it moves no money.

Going production with real rails would require, at minimum: a licensed
payment partner, credentials in a vault (never in code or chat), an HSM
for signing, and regulatory approval. None of that exists here, and
nothing here pretends otherwise.

Every class and function docstring in this module restates the boundary.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import NoReturn

import config
from cba.common import ProductionGatedError


class RailAdapter:
    """Base class for payment-rail adapters.

    BOUNDARY: this class (and every subclass) is inert. It holds no
    credentials, opens no connections, and moves no money. Any method
    that would act against a rail raises before doing anything.
    """

    name: str = "base"

    def _require_production(self) -> NoReturn:
        """Gate every rail touchpoint.

        Disabled (``config.RAILS_PRODUCTION`` unset/false) -> raise
        ``ProductionGatedError``: the rail is off, refusing to act.
        Enabled -> STILL raise ``NotImplementedError``: the licensed rail
        integration is not implemented in this prototype, so nothing can
        move money either way.
        """
        if not config.RAILS_PRODUCTION:  # read inside the method; tests monkeypatch it
            raise ProductionGatedError(
                f"{self.name}: production rail is disabled - refusing to act. "
                "Enable only with CBA_RAILS_PRODUCTION=1 plus a licensed "
                "integration (not implemented in this prototype)."
            )
        raise NotImplementedError(
            f"{self.name}: licensed rail integration is not implemented "
            "in this prototype."
        )


class CipsRail(RailAdapter):
    """China's Cross-Border Interbank Payment System (CIPS) for CNY clearing.

    BOUNDARY: inert adapter. No credentials, no network calls, no money
    movement. ``submit_payment`` and ``query_status`` raise instead of
    acting. Real CIPS integration needs a licensed participant bank,
    credentials in a vault, and PBoC/regulatory approval — none of which
    exist in this prototype.
    """

    name = "CIPS"

    def submit_payment(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises ``ProductionGatedError`` (rail disabled)
        or ``NotImplementedError`` (rail enabled but integration absent).
        Never submits anything."""
        self._require_production()

    def query_status(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises instead of querying anything."""
        self._require_production()


class EcnYRail(RailAdapter):
    """Digital-yuan (e-CNY) wallet rail (People's Bank of China).

    BOUNDARY: inert adapter. No wallet keys, no ledger access, no money
    movement. ``submit_payment`` and ``query_status`` raise instead of
    acting. Real e-CNY integration needs PBoC-authorized operating
    institutions, key custody in an HSM, and regulatory approval — none of
    which exist in this prototype.
    """

    name = "e-CNY"

    def submit_payment(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises ``ProductionGatedError`` (rail disabled)
        or ``NotImplementedError`` (rail enabled but integration absent).
        Never submits anything."""
        self._require_production()

    def query_status(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises instead of querying anything."""
        self._require_production()


class MBridgeRail(RailAdapter):
    """Multi-CBDC bridge (BIS Innovation Hub / participating central banks).

    BOUNDARY: inert adapter. No node access, no bridge credentials, no
    money movement. ``submit_payment`` and ``query_status`` raise instead
    of acting. Real mBridge integration needs participation through a
    central bank / authorized entity and the bridge's production
    infrastructure — none of which exist in this prototype.
    """

    name = "mBridge"

    def submit_payment(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises ``ProductionGatedError`` (rail disabled)
        or ``NotImplementedError`` (rail enabled but integration absent).
        Never submits anything."""
        self._require_production()

    def query_status(self, **kwargs) -> NoReturn:
        """BOUNDARY: inert — raises instead of querying anything."""
        self._require_production()


_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def validate_bic(bic: str) -> bool:
    """Check whether ``bic`` matches the ISO 9362 BIC format.

    BOUNDARY: format check only — it says nothing about whether the BIC
    exists, is reachable, or belongs to a licensed institution.
    """
    return isinstance(bic, str) and _BIC_RE.match(bic.strip()) is not None


def build_pain001(
    *,
    msg_id: str,
    created: str,
    debtor_name: str,
    debtor_acct: str,
    creditor_name: str,
    creditor_acct: str,
    creditor_agent_bic: str,
    amount: float,
    currency: str,
    remittance_info: str = "",
    debtor_agent_bic: str = "",
) -> str:
    """Build an ISO 20022 ``pain.001.001.03`` CustomerCreditTransferInitiation.

    BOUNDARY: FORMAT ONLY — generates the ISO 20022 message text. It is
    not transmitted, signed, or settled; generating it moves no money.

    Args:
        msg_id: message identifier (used for GrpHdr, PmtInfId, and the
            instruction / end-to-end ids).
        created: creation date-time string (e.g. ISO 8601).
        debtor_name: name of the debtor (also used as InitgPty).
        debtor_acct: debtor account identifier (emitted as IBAN element).
        creditor_name: name of the creditor.
        creditor_acct: creditor account identifier (emitted as IBAN element).
        creditor_agent_bic: BIC of the creditor's agent bank.
        amount: transfer amount, must be > 0.
        currency: 3-letter ISO currency code.
        remittance_info: optional unstructured remittance text.
        debtor_agent_bic: optional BIC of the debtor's agent bank; the
            ``DbtrAgt`` element is omitted when empty.

    Returns:
        The pain.001 XML document as a string, with XML declaration.

    Raises:
        ValueError: if ``amount`` <= 0 or ``currency`` is not 3 letters.
    """
    if not isinstance(amount, (int, float)) or amount <= 0:
        raise ValueError(f"amount must be > 0, got {amount!r}")
    if not isinstance(currency, str) or not currency.strip().isalpha() or len(currency.strip()) != 3:
        raise ValueError(f"currency must be a 3-letter code, got {currency!r}")
    currency = currency.strip().upper()
    amount_text = f"{amount:.2f}"

    doc = ET.Element("Document")
    initn = ET.SubElement(doc, "CstmrCdtTrfInitn")

    # --- Group header ---
    grp = ET.SubElement(initn, "GrpHdr")
    ET.SubElement(grp, "MsgId").text = msg_id
    ET.SubElement(grp, "CreDtTm").text = created
    ET.SubElement(grp, "NbOfTxs").text = "1"
    initg = ET.SubElement(grp, "InitgPty")
    ET.SubElement(initg, "Nm").text = debtor_name

    # --- Payment information ---
    pmt_inf = ET.SubElement(initn, "PmtInf")
    ET.SubElement(pmt_inf, "PmtInfId").text = f"{msg_id}-P1"
    ET.SubElement(pmt_inf, "PmtMtd").text = "TRF"

    dbtr = ET.SubElement(pmt_inf, "Dbtr")
    ET.SubElement(dbtr, "Nm").text = debtor_name
    dbtr_acct = ET.SubElement(pmt_inf, "DbtrAcct")
    dbtr_acct_id = ET.SubElement(dbtr_acct, "Id")
    ET.SubElement(dbtr_acct_id, "IBAN").text = debtor_acct
    if debtor_agent_bic:
        dbtr_agt = ET.SubElement(pmt_inf, "DbtrAgt")
        ET.SubElement(ET.SubElement(dbtr_agt, "FinInstnId"), "BICFI").text = debtor_agent_bic

    # --- Credit transfer transaction ---
    tx = ET.SubElement(pmt_inf, "CdtTrfTxInf")
    pmt_id = ET.SubElement(tx, "PmtId")
    ET.SubElement(pmt_id, "InstrId").text = f"{msg_id}-I1"
    ET.SubElement(pmt_id, "EndToEndId").text = f"{msg_id}-E1"

    amt = ET.SubElement(tx, "Amt")
    instd = ET.SubElement(amt, "InstdAmt", Ccy=currency)
    instd.text = amount_text

    cdtr_agt = ET.SubElement(tx, "CdtrAgt")
    ET.SubElement(ET.SubElement(cdtr_agt, "FinInstnId"), "BICFI").text = creditor_agent_bic

    cdtr = ET.SubElement(tx, "Cdtr")
    ET.SubElement(cdtr, "Nm").text = creditor_name
    cdtr_acct = ET.SubElement(tx, "CdtrAcct")
    cdtr_acct_id = ET.SubElement(cdtr_acct, "Id")
    ET.SubElement(cdtr_acct_id, "IBAN").text = creditor_acct

    if remittance_info:
        rmt = ET.SubElement(tx, "RmtInf")
        ET.SubElement(rmt, "Ustrd").text = remittance_info

    return ET.tostring(doc, encoding="utf-8", xml_declaration=True).decode("utf-8")
