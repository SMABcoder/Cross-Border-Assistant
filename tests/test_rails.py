"""Tests for cba.rails — inert adapters (double-gated) + pain.001 builder."""
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import config
from cba.common import ProductionGatedError
from cba.rails import (
    CipsRail,
    EcnYRail,
    MBridgeRail,
    RailAdapter,
    build_pain001,
    validate_bic,
)

RAILS = (CipsRail, EcnYRail, MBridgeRail)


def prod_off():
    return mock.patch.object(config, "RAILS_PRODUCTION", False)


def prod_on():
    return mock.patch.object(config, "RAILS_PRODUCTION", True)


class TestInertAdapters(unittest.TestCase):
    def test_base_adapter_is_inert_when_disabled(self):
        with prod_off():
            with self.assertRaises(ProductionGatedError):
                RailAdapter()._require_production()

    def test_submit_refuses_when_disabled(self):
        for cls in RAILS:
            with self.subTest(rail=cls.__name__):
                with prod_off():
                    with self.assertRaises(ProductionGatedError) as ctx:
                        cls().submit_payment(amount=100, currency="USD")
                    self.assertIn("refusing", str(ctx.exception))

    def test_query_status_refuses_when_disabled(self):
        for cls in RAILS:
            with self.subTest(rail=cls.__name__):
                with prod_off():
                    with self.assertRaises(ProductionGatedError):
                        cls().query_status(ref="abc")

    def test_still_inert_when_enabled(self):
        # Even with RAILS_PRODUCTION=True the adapters must refuse to act:
        # the licensed integration does not exist in this prototype.
        for cls in RAILS:
            with self.subTest(rail=cls.__name__):
                with prod_on():
                    with self.assertRaises(NotImplementedError):
                        cls().submit_payment(amount=100, currency="USD")
                with prod_on():
                    with self.assertRaises(NotImplementedError):
                        cls().query_status(ref="abc")

    def test_gate_message_names_the_rail(self):
        with prod_off():
            with self.assertRaises(ProductionGatedError) as ctx:
                CipsRail().submit_payment()
            self.assertIn("CIPS", str(ctx.exception))


class TestPain001(unittest.TestCase):
    def kwargs(self):
        return dict(
            msg_id="MSG-1",
            created="2026-10-18T22:15:00",
            debtor_name="Ayesha Khan",
            debtor_acct="PK36SCBL0000001123456789",
            creditor_name="Tsinghua University",
            creditor_acct="CN29BKCH0000001234567890",
            creditor_agent_bic="BKCHCNBJ",
            amount=1250.5,
            currency="USD",
            remittance_info="Tuition fee spring term",
        )

    def test_returns_parseable_xml(self):
        xml = build_pain001(**self.kwargs())
        root = ET.fromstring(xml)  # raises if malformed
        # pain.001 root is Document; the payload is its child.
        self.assertEqual(root.tag, "Document")
        self.assertTrue(root[0].tag.endswith("CstmrCdtTrfInitn"))

    def test_contains_party_names_amount_and_ccy(self):
        xml = build_pain001(**self.kwargs())
        self.assertIn("Ayesha Khan", xml)
        self.assertIn("Tsinghua University", xml)
        self.assertIn("1250.50", xml)  # two decimals
        self.assertIn('Ccy="USD"', xml)
        self.assertIn("BKCHCNBJ", xml)

    def test_optional_remittance_and_debtor_agent(self):
        kw = self.kwargs()
        kw.pop("remittance_info")
        xml = build_pain001(**kw)
        self.assertNotIn("RmtInf", xml)
        self.assertNotIn("DbtrAgt", xml)
        xml2 = build_pain001(**{**kw, "debtor_agent_bic": "DEUTDEFF"})
        self.assertIn("DbtrAgt", xml2)

    def test_zero_and_negative_amount_rejected(self):
        for bad in (0, -1, -0.01):
            kw = self.kwargs()
            kw["amount"] = bad
            with self.assertRaises(ValueError):
                build_pain001(**kw)

    def test_bad_currency_rejected(self):
        for bad in ("US", "USDD", "12", "", "U$D"):
            kw = self.kwargs()
            kw["currency"] = bad
            with self.assertRaises(ValueError):
                build_pain001(**kw)


class TestValidateBic(unittest.TestCase):
    def test_valid_bics(self):
        self.assertTrue(validate_bic("BKCHCNBJ"))
        self.assertTrue(validate_bic("BKCHCNBJ300"))

    def test_invalid_bics(self):
        self.assertFalse(validate_bic("nope"))
        self.assertFalse(validate_bic("BKCHC"))
        self.assertFalse(validate_bic(""))


if __name__ == "__main__":
    unittest.main()
