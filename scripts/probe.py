"""Read one VW portal dataset; save field availability without personal values."""
import getpass
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from carconnectivity.errors import TooManyRequestsError
from carconnectivity_connectors.vw_eu_data_act.client import (
    EudaApiClient, AuthError, ApiError, NO_CONTENT_SUFFIX,
)
from carconnectivity_connectors.vw_eu_data_act.dataset import Dataset, parse_timestamp
from requests.exceptions import RequestException

ROOT = Path(__file__).resolve().parents[1]


class ProbeRequestError(Exception):
    """A fixed diagnostic with no upstream URL, body or identifier."""


def request_step(stage, operation, *args):
    print(f"Reading {stage}...")
    try:
        return operation(*args)
    except (AuthError, TooManyRequestsError):
        raise
    except (ApiError, RequestException) as error:
        # The pinned client appends status to its errors; never print the prefix.
        match = re.search(r" -> HTTP ([45][0-9]{2})$", str(error))
        status = int(match.group(1)) if match else None
        response = getattr(error, "response", None)
        if response is not None:
            status = response.status_code
        detail = f"HTTP {status}" if isinstance(status, int) and 400 <= status <= 599 else "network or response error"
        hint = "Check whether the VW portal can display and download a continuous dataset."
        if status == 404 and stage == "continuous request metadata":
            hint = "VW could not find this continuous request endpoint/resource. Confirm a continuous (not one-off) request exists and has produced a dataset; the integration endpoint may also have changed."
        elif status in (401, 403):
            hint = "Vehicle listing succeeded but this data request was refused. Check portal consent and access to the dataset."
        elif status is not None and status >= 500:
            hint = "VW returned a server error. Check the portal and try again later."
        raise ProbeRequestError(f"Failed at {stage}: {detail}. {hint}") from None


def latest_dataset(listing):
    """Only download a dated content file; never guess ordering from filenames."""
    candidates = []
    for item in listing:
        name = item.get("name")
        stamp = parse_timestamp(item.get("createdOn"))
        if isinstance(name, str) and name.endswith(".zip") and not name.endswith(NO_CONTENT_SUFFIX) and stamp:
            candidates.append((stamp, name))
    return max(candidates)[1] if candidates else None


def summarize(payload):
    dataset = Dataset.from_json(payload)
    return {
        "schemaVersion": 1,
        "source": "VW EU Data Act portal",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "note": "Field availability in one dataset only. No vehicle values or identifiers included.",
        "fields": [
            {"name": name, "hasValue": dataset.by_field(name).value is not None}
            for name in sorted(dataset.field_names)
        ],
    }


def inspect_vehicle(client, vin):
    metadata = request_step("continuous request metadata", client.get_metadata, vin)
    identifier = metadata.get("Identifier") or metadata.get("identifier")
    if not identifier:
        raise ValueError("No continuous request found. Enable a 15-minute continuous request on the VW portal.")
    listing = request_step("dataset listing", client.list_datasets, vin, identifier)
    print(f"Dataset listing returned {len(listing)} entries.")
    filename = latest_dataset(listing)
    if filename is None:
        raise ValueError("No dated dataset with content is available yet. Wait for the portal to generate one, then retry manually.")
    return summarize(request_step("dataset download", client.download_dataset, vin, identifier, filename))


def main():
    # Upstream debug messages may contain account identifiers or response bodies.
    logging.disable(logging.CRITICAL)
    print("MMM-VWCar-BODK: local read-only connection test")
    print("First enable continuous data at https://eu-data-act.drivesomethinggreater.com/")
    print("Credentials are used in memory only. No vehicle commands are sent.")
    client = None
    try:
        email = input("Volkswagen ID email: ").strip()
        password = getpass.getpass("Volkswagen ID password (hidden): ")
        if not email or not password:
            print("Email and password are required.")
            return 1
        client = EudaApiClient(email, password, country="dk", language="en", timeout=30,
                               accept_terms_on_login=False)
        print("Connecting to the VW portal...")
        vehicles = client.list_vehicles()
        if not vehicles:
            print("Login succeeded, but no consented vehicles were found. Connect your car on the portal.")
            return 2
        for index, vehicle in enumerate(vehicles, 1):
            print(f"{index}: vehicle VIN ending {vehicle['vin'][-4:]}")
        selected = 0
        if len(vehicles) > 1:
            choice = input("Vehicle number to inspect: ").strip()
            if not choice.isdigit() or not 1 <= int(choice) <= len(vehicles):
                print("Invalid vehicle number.")
                return 1
            selected = int(choice) - 1
        report = inspect_vehicle(client, vehicles[selected]["vin"])
        if not report["fields"]:
            print("A dataset was downloaded, but no fields were recognized. The data format may have changed.")
            return 3
        folder = ROOT / "private"
        folder.mkdir(exist_ok=True)
        destination = folder / "availability.json"
        destination.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Success: {len(report['fields'])} fields found in the latest dataset.")
        print(f"Field availability report: {destination}")
        print("This is a single snapshot; absent fields may appear in later datasets.")
        return 0
    except AuthError:
        print("VW login did not complete. Check credentials and complete any MFA or consent screens on the portal in your browser. Automated login may still be unsupported.")
        return 4
    except TooManyRequestsError:
        print("VW rate limit reached. Stop testing and try again later.")
        return 5
    except ProbeRequestError as error:
        print(error)
        print("No automatic probe retry will run. You can share these diagnostic lines without sharing your login.")
        return 6
    except (ApiError, RequestException):
        print("VW data request failed. Check network access and that the portal contains a continuous dataset. No automatic probe retry will run.")
        return 6
    except ValueError as error:
        # Only our fixed local messages are exposed; upstream parsing errors may contain private data.
        message = str(error)
        if message.startswith(("No continuous request found.", "No dated dataset with content")):
            print(message)
        else:
            print("The portal returned an unexpected data format.")
        return 7
    except (KeyboardInterrupt, EOFError):
        print("\nTest cancelled.")
        return 130
    except Exception:
        print("Unexpected integration error. No private exception details were printed.")
        return 8
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
