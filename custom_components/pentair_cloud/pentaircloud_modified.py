"""Modified Pentair Cloud API with concurrent program support."""
from pycognito import Cognito
from homeassistant.core import HomeAssistant
import boto3
import requests
from logging import Logger
from requests_aws4auth import AWS4Auth
from homeassistant.components.light import ATTR_BRIGHTNESS, PLATFORM_SCHEMA, LightEntity
import time
import json
from .const import DEBUG_INFO

AWS_REGION = "us-west-2"
AWS_USER_POOL_ID = "us-west-2_lbiduhSwD"
AWS_CLIENT_ID = "3de110o697faq7avdchtf07h4v"
AWS_IDENTITY_POOL_ID = "us-west-2:6f950f85-af44-43d9-b690-a431f753e9aa"
AWS_COGNITO_ENDPOINT = "cognito-idp.us-west-2.amazonaws.com"
PENTAIR_ENDPOINT = "https://api.pentair.cloud"
PENTAIR_USER_PROFILE_PATH = "/user/user-service/common/profilev2"
PENTAIR_DEVICES_PATH = "/device/device-service/user/devices"
PENTAIR_DEVICES_2_PATH = "/device2/device2-service/user/device"
PENTAIR_DEVICE_SERVICE_PATH = "/device/device-service/user/device/"
UPDATE_MIN_SECONDS = 60  # Minimum time between two update requests
PROGRAM_START_MIN_SECONDS = 5  # Reduced for concurrent activation


class PentairPumpProgram:
    def __init__(
        self, id: int, name: str, program_type: int, control_value: int = 0
    ) -> None:
        self.id = id
        self.name = name
        self.program_type = program_type  # 0=Schedule, 1=Interval, 2=Manual
        self.control_value = control_value  # e10 value (0=inactive, 3=active)
        self.running = control_value == 3

    def get_start_value(self) -> int:
        return 3

    def get_stop_value(self) -> int:
        return 0  # Changed to 0 for clean deactivation


class PentairDevice:
    def __init__(self, LOGGER: Logger, pentair_device_id: str, nickname: str) -> None:
        self.LOGGER = LOGGER
        self.pentair_device_id = pentair_device_id
        self.nickname = nickname
        self.status = False
        self.last_program_start = None
        self.active_pump_program = None  # s14 - which program controls the pump
        self.programs = []
        self.pump_running = False
        self.relay1_on = False
        self.relay2_on = False
        self.motor_speed = 0
        self.power = 0
        self.flow_rate = 0

    def update_program(
        self, id: int, name: str, program_type: int, control_value: int
    ) -> None:
        exists = False
        for program in self.programs:
            if program.id == id:  # update
                exists = True
                program.name = name
                program.program_type = program_type
                program.control_value = control_value
                program.running = control_value == 3
                if DEBUG_INFO:
                    self.LOGGER.info(
                        f"Update program for device {self.pentair_device_id} / "
                        f"{id} - {name} (e10={control_value})"
                    )
        if not exists:
            self.programs.append(
                PentairPumpProgram(id, name, program_type, control_value)
            )
            if DEBUG_INFO:
                self.LOGGER.info(
                    f"Found new program for device {self.pentair_device_id} / "
                    f"{id} - {name}"
                )

    def get_other_relay_state(self, relay_number: int) -> bool:
        """Get the state of the other relay."""
        if relay_number == 1:
            return self.relay2_on
        else:
            return self.relay1_on


class PentairCloudHub:
    global AWS_USER_POOL_ID
    global AWS_CLIENT_ID
    global AWS_REGION
    global AWS_COGNITO_ENDPOINT
    global AWS_USER_POOL_ID
    global AWS_IDENTITY_POOL_ID
    global PENTAIR_ENDPOINT
    global PENTAIR_DEVICES_PATH
    global PENTAIR_DEVICES_2_PATH
    global PENTAIR_DEVICE_SERVICE_PATH
    global UPDATE_MIN_SECONDS
    global PROGRAM_START_MIN_SECONDS

    def __init__(
        self,
        LOGGER: Logger,
    ) -> None:
        self.cognito_client = None
        self.LOGGER = LOGGER
        self.AWS_TOKEN = None
        self.AWS_IDENTITY_ID = None
        self.AWS_ACCESS_KEY_ID = None
        self.AWS_SECRET_ACCESS_KEY = None
        self.AWS_SESSION_TOKEN = None
        self.last_update = None
        self.username = None
        self.password = None
        self.devices = []

    def get_cognito_client(self, usr: str) -> Cognito:
        return Cognito(AWS_USER_POOL_ID, AWS_CLIENT_ID, username=usr)

    def get_devices(self) -> list[PentairDevice]:
        return self.devices

    def populate_AWS_token(self) -> None:
        if self.cognito_client is not None:
            self.cognito_client.check_token()
            new_token = self.cognito_client.get_user()._metadata["id_token"]
            if self.AWS_TOKEN != new_token:  # Token has been refreshed
                self.AWS_TOKEN = new_token
                self.populate_AWS_and_data_fields()

    def populate_AWS_and_data_fields(self) -> None:
        if self.AWS_TOKEN is None:
            self.populate_AWS_token()
        try:
            client = boto3.client("cognito-identity", region_name=AWS_REGION)
            # IdentityId
            response = client.get_id(
                IdentityPoolId=AWS_IDENTITY_POOL_ID,
                Logins={AWS_COGNITO_ENDPOINT + "/" + AWS_USER_POOL_ID: self.AWS_TOKEN},
            )
            self.AWS_IDENTITY_ID = response["IdentityId"]
            # Credentials for Identity
            response = client.get_credentials_for_identity(
                IdentityId=self.AWS_IDENTITY_ID,
                Logins={AWS_COGNITO_ENDPOINT + "/" + AWS_USER_POOL_ID: self.AWS_TOKEN},
            )
            self.AWS_ACCESS_KEY_ID = response["Credentials"]["AccessKeyId"]
            self.AWS_SECRET_ACCESS_KEY = response["Credentials"]["SecretKey"]
            self.AWS_SESSION_TOKEN = response["Credentials"]["SessionToken"]
            if DEBUG_INFO:
                self.LOGGER.info("Pentair Cloud complete Populate AWS Fields")
            self.populate_pentair_devices()
        except Exception as err:
            self.LOGGER.error(
                "Exception while setting up Pentair Cloud (Populate AWS Fields). %s",
                err,
            )

    def get_pentair_header(self) -> str:
        return {
            "x-amz-id-token": self.AWS_TOKEN,
            "user-agent": "aws-amplify/4.3.10 react-native",
            "content-type": "application/json; charset=UTF-8",
        }

    def get_AWS_auth(self) -> AWS4Auth:
        return AWS4Auth(
            self.AWS_ACCESS_KEY_ID,
            self.AWS_SECRET_ACCESS_KEY,
            AWS_REGION,
            "execute-api",
            session_token=self.AWS_SESSION_TOKEN,
        )

    def populate_pentair_devices(self) -> None:
        if self.AWS_TOKEN is not None:
            try:
                # GetDeviceConfiguration
                endpoint = PENTAIR_ENDPOINT + PENTAIR_DEVICES_PATH
                response = requests.get(
                    endpoint,
                    auth=self.get_AWS_auth(),
                    headers=self.get_pentair_header(),
                )
                for device in response.json()["data"]:
                    if device["deviceType"] == "IF31":
                        if device["status"] == "ACTIVE":
                            self.devices.append(
                                PentairDevice(
                                    self.LOGGER,
                                    device["deviceId"],
                                    device["productInfo"]["nickName"],
                                )
                            )
                            if DEBUG_INFO:
                                self.LOGGER.info(
                                    "Found compatible device:" + device["deviceId"]
                                )
                        else:
                            if DEBUG_INFO:
                                self.LOGGER.warning(
                                    "Found inactive device:" + device["deviceId"]
                                )
                    else:
                        if DEBUG_INFO:
                            self.LOGGER.warning(
                                "Incompatible device"
                                + device["deviceType"]
                                + "/"
                                + device["pname"]
                            )
                self.update_pentair_devices_status()
            except Exception as err:
                self.LOGGER.error(
                    "Exception while setting up Pentair Cloud (Populate Pentair Device ID). %s",
                    err,
                )
        else:
            self.LOGGER.error(
                "Exception while setting up Pentair Cloud (Empty token in populate Pentair Device ID)."
            )

    def update_pentair_devices_status(self) -> None:
        if (
            self.last_update == None
            or time.time() - self.last_update > UPDATE_MIN_SECONDS
        ):
            if DEBUG_INFO:
                self.LOGGER.info("Pentair Cloud - Update Devices Status")
            self.last_update = time.time()
            self.populate_AWS_token()
            if self.AWS_TOKEN is not None:
                try:
                    devices_json_list = []
                    for device in self.devices:
                        devices_json_list.append('"' + device.pentair_device_id + '"')
                    devices_json = (
                        '{"deviceIds": [' + ",".join(devices_json_list) + "]}"
                    )
                    endpoint = PENTAIR_ENDPOINT + PENTAIR_DEVICES_2_PATH
                    response = requests.post(
                        endpoint,
                        auth=self.get_AWS_auth(),
                        headers=self.get_pentair_header(),
                        data=devices_json,
                    )
                    response_data = response.json()
                    for device_response in response_data["response"]["data"]:
                        for device in self.devices:
                            if device.pentair_device_id == device_response["deviceId"]:
                                fields = device_response["fields"]
                                
                                # Update device status fields
                                device.active_pump_program = int(fields.get("s14", {}).get("value", "99"))
                                if device.active_pump_program == 99:
                                    device.active_pump_program = None
                                else:
                                    device.active_pump_program += 1  # Convert from 0-based to 1-based
                                
                                device.pump_running = device.active_pump_program is not None
                                device.motor_speed = int(fields.get("s19", {}).get("value", "0")) / 10
                                device.power = int(fields.get("s18", {}).get("value", "0"))
                                device.flow_rate = int(fields.get("s26", {}).get("value", "0")) / 10
                                # Keep physical relay status for reference
                                device.relay1_on = fields.get("s21", {}).get("value", "0") == "1"
                                device.relay2_on = fields.get("s22", {}).get("value", "0") == "1"
                                
                                # Update program states
                                for i in range(1, 9):
                                    if fields.get(f"zp{i}e13", {}).get("value") == "1":  # Program is active
                                        program_type = int(fields.get(f"zp{i}e5", {}).get("value", "0"))
                                        control_value = int(fields.get(f"zp{i}e10", {}).get("value", "0"))
                                        device.update_program(
                                            i,
                                            fields.get(f"zp{i}e2", {}).get("value", f"Program {i}"),
                                            program_type,
                                            control_value
                                        )

                except Exception as err:
                    self.LOGGER.error(
                        "Exception while updating Pentair Cloud (update device status). %s, %s",
                        err,
                        response_data,
                    )
                    try:
                        self.LOGGER.error("Timeout detected. Logging Again")
                        if "timeout" in response_data["message"]:
                            self.authenticate(
                                self.username, self.password
                            )  # Refresh authentication in case of timeout
                    except Exception as err2:
                        self.LOGGER.error(
                            "ERROR in Timeout detection loop.",
                            err2,
                        )
            else:
                self.LOGGER.error(
                    "Exception while updating Pentair Cloud (Empty token in device status)."
                )
        else:
            if DEBUG_INFO:
                self.LOGGER.info(
                    "Pentair Cloud - Update Devices Status Requested but before min time"
                )

    def activate_program_concurrent(self, deviceId: str, program_id: int) -> None:
        """Activate a program allowing concurrent activation."""
        if DEBUG_INFO:
            self.LOGGER.info(
                f"Pentair Cloud - Activating program {program_id} on device {deviceId}"
            )
        
        self.populate_AWS_token()
        if self.AWS_TOKEN is not None:
            try:
                endpoint = PENTAIR_ENDPOINT + PENTAIR_DEVICE_SERVICE_PATH + deviceId
                field_name = f"zp{program_id}e10"
                payload = {"payload": {field_name: "3"}}
                
                if DEBUG_INFO:
                    self.LOGGER.info(f"Sending payload: {payload} to {endpoint}")
                
                response = requests.put(
                    endpoint,
                    auth=self.get_AWS_auth(),
                    headers=self.get_pentair_header(),
                    data=json.dumps(payload),
                )
                
                if DEBUG_INFO:
                    self.LOGGER.info(f"Response status: {response.status_code}")
                    self.LOGGER.info(f"Response body: {response.text}")
                
                response_data = response.json()
                if response_data.get("data", {}).get("code") != "set_device_success":
                    self.LOGGER.error(f"Failed to activate program: {response_data}")
                    raise Exception("Wrong response code activating program")
                
                # Find and update the program state
                for device in self.devices:
                    if device.pentair_device_id == deviceId:
                        for program in device.programs:
                            if program.id == program_id:
                                program.running = True
                                program.control_value = 3
                
            except Exception as err:
                self.LOGGER.error(
                    "Exception with Pentair API (Activate Program). %s",
                    err,
                )
        else:
            self.LOGGER.error(
                "Exception while activating program (Empty token)."
            )

    def deactivate_program(self, deviceId: str, program_id: int) -> None:
        """Deactivate a specific program."""
        if DEBUG_INFO:
            self.LOGGER.info(
                f"Pentair Cloud - Deactivating program {program_id} on device {deviceId}"
            )
        
        self.populate_AWS_token()
        if self.AWS_TOKEN is not None:
            try:
                endpoint = PENTAIR_ENDPOINT + PENTAIR_DEVICE_SERVICE_PATH + deviceId
                field_name = f"zp{program_id}e10"
                payload = {"payload": {field_name: "0"}}
                
                response = requests.put(
                    endpoint,
                    auth=self.get_AWS_auth(),
                    headers=self.get_pentair_header(),
                    data=json.dumps(payload),
                )
                
                response_data = response.json()
                if response_data["data"]["code"] != "set_device_success":
                    raise Exception("Wrong response code deactivating program")
                
                # Update program state
                for device in self.devices:
                    if device.pentair_device_id == deviceId:
                        for program in device.programs:
                            if program.id == program_id:
                                program.running = False
                                program.control_value = 0
                
            except Exception as err:
                self.LOGGER.error(
                    "Exception with Pentair API (Deactivate Program). %s",
                    err,
                )

    def stop_all_programs(self, deviceId: str) -> None:
        """Stop all programs on a device."""
        if DEBUG_INFO:
            self.LOGGER.info(f"Stopping all programs on device {deviceId}")
        
        for i in range(1, 9):
            self.deactivate_program(deviceId, i)

    def start_program(self, deviceId: str, program_id: int) -> None:
        """Legacy method - redirects to concurrent activation."""
        self.activate_program_concurrent(deviceId, program_id)

    def stop_program(self, deviceId: str, program_id: int) -> None:
        """Legacy method - redirects to deactivation."""
        self.deactivate_program(deviceId, program_id)

    def authenticate(self, username: str, password: str) -> bool:
        try:
            u = self.get_cognito_client(username)
            u.authenticate(password)
            self.cognito_client = u
            self.cognito_client.get_user()
            self.username = username
            self.password = password
            return True

        except Exception as err:
            self.LOGGER.error("Exception while logging with Pentair Cloud. %s", err)
            return False