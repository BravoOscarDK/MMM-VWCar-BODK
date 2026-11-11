"""Offline checks; these do not verify VW account or vehicle access."""
import json
import unittest
from unittest.mock import Mock
from scripts.probe import inspect_vehicle, latest_dataset, summarize, request_step, ProbeRequestError
from carconnectivity_connectors.vw_eu_data_act.client import ApiError, AuthError
from requests.exceptions import ConnectionError


class ProbeTests(unittest.TestCase):
    def test_metadata_failure_is_specific_and_private(self):
        client = Mock()
        client.get_metadata.side_effect = ApiError("https://example.invalid/PRIVATE_VIN?token=SECRET -> HTTP 404")
        with self.assertRaises(ProbeRequestError) as caught:
            inspect_vehicle(client, "PRIVATE_VIN")
        text = str(caught.exception)
        self.assertIn("continuous request metadata: HTTP 404", text)
        self.assertNotIn("PRIVATE_VIN", text)
        self.assertNotIn("SECRET", text)
        client.list_datasets.assert_not_called()

    def test_download_failure_identifies_stage(self):
        client = Mock()
        client.get_metadata.return_value = {"Identifier": "REQUEST"}
        client.list_datasets.return_value = [{"name": "data.zip", "createdOn": "2026-11-10T10:00:00Z"}]
        client.download_dataset.side_effect = ApiError("Download PRIVATE_FILE -> HTTP 503")
        with self.assertRaisesRegex(ProbeRequestError, "dataset download: HTTP 503"):
            inspect_vehicle(client, "EXAMPLE")

    def test_network_error_hides_upstream_text(self):
        with self.assertRaises(ProbeRequestError) as caught:
            request_step("dataset listing", Mock(side_effect=ConnectionError("PRIVATE_URL")))
        self.assertIn("network or response error", str(caught.exception))
        self.assertNotIn("PRIVATE_URL", str(caught.exception))

    def test_auth_error_keeps_existing_handler(self):
        with self.assertRaises(AuthError):
            request_step("dataset listing", Mock(side_effect=AuthError("private")))

    def test_latest_content_by_timestamp(self):
        self.assertEqual(latest_dataset([
            {"name": "old.zip", "createdOn": "2026-11-10T09:00:00Z"},
            {"name": "empty_no_content_found.zip", "createdOn": "2026-11-10T11:00:00Z"},
            {"name": "new.zip", "createdOn": "2026-11-10T10:00:00Z"},
            {"name": "undated.zip"},
        ]), "new.zip")

    def test_empty_listing(self):
        self.assertIsNone(latest_dataset([]))

    def test_report_excludes_values_and_identifiers(self):
        result = summarize({"vin": "PRIVATE_VIN", "user_id": "PRIVATE_ACCOUNT", "Data": [
            {"key": "a", "dataFieldName": "battery", "value": "0"},
            {"key": "b", "dataFieldName": "locked", "value": "false"},
            {"key": "c", "dataFieldName": "nickname", "value": "PRIVATE_NAME"},
        ]})
        serialized = json.dumps(result)
        for secret in ("PRIVATE_VIN", "PRIVATE_ACCOUNT", "PRIVATE_NAME"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(all(field["hasValue"] for field in result["fields"]))

    def test_missing_request_does_not_download(self):
        client = Mock()
        client.get_metadata.return_value = {}
        with self.assertRaisesRegex(ValueError, "No continuous request"):
            inspect_vehicle(client, "EXAMPLE")
        client.download_dataset.assert_not_called()

    def test_one_dataset_downloaded(self):
        client = Mock()
        client.get_metadata.return_value = {"Identifier": "REQUEST"}
        client.list_datasets.return_value = [{"name": "data.zip", "createdOn": "2026-11-10T10:00:00Z"}]
        client.download_dataset.return_value = {"Data": []}
        self.assertEqual(inspect_vehicle(client, "EXAMPLE")["fields"], [])
        client.download_dataset.assert_called_once_with("EXAMPLE", "REQUEST", "data.zip")


if __name__ == "__main__":
    unittest.main()
