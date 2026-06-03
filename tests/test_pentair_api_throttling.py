import importlib.util
import sys
import types
from pathlib import Path


def install_import_stubs():
    pycognito = types.ModuleType("pycognito")
    pycognito.Cognito = object
    sys.modules["pycognito"] = pycognito

    boto3 = types.ModuleType("boto3")
    boto3.client = lambda *args, **kwargs: None
    sys.modules["boto3"] = boto3

    requests = types.ModuleType("requests")
    requests.get = lambda *args, **kwargs: None
    requests.post = lambda *args, **kwargs: None
    requests.put = lambda *args, **kwargs: None
    sys.modules["requests"] = requests

    requests_aws4auth = types.ModuleType("requests_aws4auth")
    requests_aws4auth.AWS4Auth = lambda *args, **kwargs: ("auth", args, kwargs)
    sys.modules["requests_aws4auth"] = requests_aws4auth

    homeassistant = types.ModuleType("homeassistant")
    homeassistant.core = types.ModuleType("homeassistant.core")
    homeassistant.core.HomeAssistant = object
    components = types.ModuleType("homeassistant.components")
    fan = types.ModuleType("homeassistant.components.fan")
    fan.FanEntity = object
    fan.FanEntityFeature = types.SimpleNamespace(TURN_ON=1, TURN_OFF=16, SET_SPEED=32)
    light = types.ModuleType("homeassistant.components.light")
    light.ATTR_BRIGHTNESS = "brightness"
    light.PLATFORM_SCHEMA = object()
    light.LightEntity = object
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    const = types.ModuleType("homeassistant.const")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    helpers.entity_platform.AddEntitiesCallback = object
    helpers.update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __init__(self, coordinator=None):
            self.coordinator = coordinator

    helpers.update_coordinator.CoordinatorEntity = CoordinatorEntity
    exceptions = types.ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = Exception
    homeassistant.core.callback = lambda func: func
    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.core"] = homeassistant.core
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.fan"] = fan
    sys.modules["homeassistant.components.light"] = light
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.const"] = const
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity_platform"] = helpers.entity_platform
    sys.modules["homeassistant.helpers.update_coordinator"] = helpers.update_coordinator
    sys.modules["homeassistant.exceptions"] = exceptions


class FakeLogger:
    def __init__(self):
        self.errors = []
        self.infos = []

    def error(self, *args):
        self.errors.append(args)

    def info(self, *args):
        self.infos.append(args)


class FakeCognitoClient:
    def __init__(self):
        self.id_token = "fresh-id-token"
        self.check_token_calls = 0
        self.get_user_calls = 0

    def check_token(self):
        self.check_token_calls += 1

    def get_user(self):
        self.get_user_calls += 1
        raise AssertionError("refresh should not call Cognito GetUser")


def import_pentair_module(filename="pentaircloud_modified.py"):
    install_import_stubs()
    stem = Path(filename).stem
    module_name = f"custom_components.pentair_cloud.{stem}"
    sys.modules.pop(module_name, None)

    root = Path("custom_components/pentair_cloud").resolve()
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(root.parent)]
    pentair_package = types.ModuleType("custom_components.pentair_cloud")
    pentair_package.__path__ = [str(root)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.pentair_cloud"] = pentair_package

    spec = importlib.util.spec_from_file_location(module_name, root / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def import_package_module(stem):
    install_import_stubs()
    module_name = f"custom_components.pentair_cloud.{stem}"
    sys.modules.pop(module_name, None)

    root = Path("custom_components/pentair_cloud").resolve()
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(root.parent)]
    pentair_package = types.ModuleType("custom_components.pentair_cloud")
    pentair_package.__path__ = [str(root)]
    sys.modules["custom_components"] = custom_components
    sys.modules["custom_components.pentair_cloud"] = pentair_package

    spec = importlib.util.spec_from_file_location(module_name, root / f"{stem}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_token_refresh_uses_cached_id_token_without_get_user():
    for filename in ["pentaircloud_modified.py", "pentaircloud.py"]:
        mod = import_pentair_module(filename)
        hub = mod.PentairCloudHub(FakeLogger())
        hub.cognito_client = FakeCognitoClient()
        hub.AWS_TOKEN = "stale-id-token"

        changed = hub.populate_AWS_token()

        assert changed is True
        assert hub.AWS_TOKEN == "fresh-id-token"
        assert hub.cognito_client.check_token_calls == 1
        assert hub.cognito_client.get_user_calls == 0


def test_status_update_refreshes_aws_credentials_when_id_token_changes(monkeypatch):
    for filename in ["pentaircloud_modified.py", "pentaircloud.py"]:
        mod = import_pentair_module(filename)
        logger = FakeLogger()
        hub = mod.PentairCloudHub(logger)
        hub.cognito_client = FakeCognitoClient()
        hub.AWS_TOKEN = "stale-id-token"
        hub.AWS_IDENTITY_ID = "stale-identity"
        hub.AWS_ACCESS_KEY_ID = "stale-key"
        hub.AWS_SECRET_ACCESS_KEY = "stale-secret"
        hub.AWS_SESSION_TOKEN = "stale-session"
        hub.devices = [mod.PentairDevice(logger, "device-1", "Pump")]

        class CognitoIdentityClient:
            def get_id(self, **kwargs):
                token = next(iter(kwargs["Logins"].values()))
                assert token == "fresh-id-token"
                return {"IdentityId": "fresh-identity"}

            def get_credentials_for_identity(self, **kwargs):
                token = next(iter(kwargs["Logins"].values()))
                assert kwargs["IdentityId"] == "fresh-identity"
                assert token == "fresh-id-token"
                return {
                    "Credentials": {
                        "AccessKeyId": "fresh-key",
                        "SecretKey": "fresh-secret",
                        "SessionToken": "fresh-session",
                    }
                }

        class StatusResponse:
            def json(self):
                return {"response": {"data": []}}

        captured = {}

        def post_status(*args, **kwargs):
            captured["auth"] = kwargs["auth"]
            captured["headers"] = kwargs["headers"]
            return StatusResponse()

        monkeypatch.setattr(mod.boto3, "client", lambda *args, **kwargs: CognitoIdentityClient())
        monkeypatch.setattr(mod.requests, "post", post_status)

        hub.update_pentair_devices_status()

        assert hub.AWS_TOKEN == "fresh-id-token"
        assert hub.AWS_ACCESS_KEY_ID == "fresh-key"
        assert hub.AWS_SECRET_ACCESS_KEY == "fresh-secret"
        assert hub.AWS_SESSION_TOKEN == "fresh-session"
        assert captured["headers"]["x-amz-id-token"] == "fresh-id-token"
        assert captured["auth"][1][0] == "fresh-key"
        assert captured["auth"][1][1] == "fresh-secret"
        assert captured["auth"][2]["session_token"] == "fresh-session"


def test_status_update_logs_api_json_errors_without_unbound_response_data(monkeypatch):
    for filename in ["pentaircloud_modified.py", "pentaircloud.py"]:
        mod = import_pentair_module(filename)
        logger = FakeLogger()
        hub = mod.PentairCloudHub(logger)
        hub.AWS_TOKEN = "token"
        hub.AWS_ACCESS_KEY_ID = "key"
        hub.AWS_SECRET_ACCESS_KEY = "secret"
        hub.AWS_SESSION_TOKEN = "session"
        hub.devices = [mod.PentairDevice(logger, "device-1", "Pump")]

        class BadResponse:
            status_code = 429
            text = "rate limited"

            def json(self):
                raise RuntimeError("rate limited json error")

        monkeypatch.setattr(mod.requests, "post", lambda *args, **kwargs: BadResponse())

        hub.update_pentair_devices_status()

        assert logger.errors
        assert "rate limited json error" in str(logger.errors[0])


def test_device_population_replaces_existing_devices_instead_of_appending(monkeypatch):
    for filename in ["pentaircloud_modified.py", "pentaircloud.py"]:
        mod = import_pentair_module(filename)
        logger = FakeLogger()
        hub = mod.PentairCloudHub(logger)
        hub.AWS_TOKEN = "token"
        hub.AWS_ACCESS_KEY_ID = "key"
        hub.AWS_SECRET_ACCESS_KEY = "secret"
        hub.AWS_SESSION_TOKEN = "session"
        hub.devices = [mod.PentairDevice(logger, "device-1", "Existing Pump")]

        class DevicesResponse:
            def json(self):
                return {
                    "data": [
                        {
                            "deviceType": "IF31",
                            "status": "ACTIVE",
                            "deviceId": "device-1",
                            "productInfo": {"nickName": "Pool Pump"},
                        }
                    ]
                }

        monkeypatch.setattr(mod.requests, "get", lambda *args, **kwargs: DevicesResponse())
        monkeypatch.setattr(hub, "update_pentair_devices_status", lambda: None)

        hub.populate_pentair_devices()

        assert len(hub.devices) == 1
        assert hub.devices[0].nickname == "Pool Pump"


def test_polling_intervals_are_rate_limit_friendly():
    coordinator = Path("custom_components/pentair_cloud/coordinator.py").read_text()

    assert "SCAN_INTERVAL = timedelta(minutes=2)" in coordinator
    for filename in ["pentaircloud_modified.py", "pentaircloud.py"]:
        hub = Path(f"custom_components/pentair_cloud/{filename}").read_text()
        assert "UPDATE_MIN_SECONDS = 60" in hub


def test_climate_uses_coordinator_instead_of_direct_polling():
    climate = Path("custom_components/pentair_cloud/climate.py").read_text()

    assert "CoordinatorEntity" in climate
    assert "def update(self)" not in climate
    assert "self._hub.update_pentair_devices_status()" not in climate


def test_fan_exposes_slider_without_homekit_preset_switches():
    fan = Path("custom_components/pentair_cloud/fan.py").read_text()

    assert "FanEntityFeature.SET_SPEED" in fan
    assert "FanEntityFeature.PRESET_MODE" not in fan
    assert "def preset_modes" not in fan
    assert "def preset_mode" not in fan


def test_fan_slider_snaps_to_real_pentair_speed_programs():
    fan = Path("custom_components/pentair_cloud/fan.py").read_text()

    assert "SLIDER_DEBOUNCE_SECONDS = 2.0" in fan
    assert "SPEED_STEPS = (0, 25, 50, 75, 100)" in fan
    assert "def _snap_requested_speed" in fan
    assert "actual_speed = self._snap_requested_speed(speed)" in fan


def test_fan_reports_percent_speed_when_pentair_motor_speed_is_percent_like():
    mod = import_package_module("fan")
    device = types.SimpleNamespace(
        nickname="Pool",
        pentair_device_id="device-1",
        active_pump_program=2,
        motor_speed=50.0,
        power=423,
        flow_rate=35.4,
        relay1_on=False,
        relay2_on=True,
        programs=[
            types.SimpleNamespace(id=6, name="Heater", running=True),
        ],
    )

    fan = mod.PentairPumpFan(
        hub=types.SimpleNamespace(),
        device=device,
        coordinator=None,
        hass=types.SimpleNamespace(),
        program_mappings={"low": 3, "medium": 7, "high": 4, "max": 5},
    )

    assert fan.is_on is True
    assert fan.percentage == 50


def test_raw_pentair_program_lights_are_not_created():
    light = Path("custom_components/pentair_cloud/light.py").read_text()

    assert "for program in device.programs:" not in light
    assert "PentairProgramLight(" not in light


def test_pool_thermostat_starts_pump_before_heater_program():
    climate = Path("custom_components/pentair_cloud/climate.py").read_text()

    pump_start = climate.index("await self._pump_fan.async_set_percentage(50)")
    heater_start = climate.index("self._hub.activate_program_concurrent", pump_start)

    assert "self._pump_fan.update_heater_state(True)" in climate
    assert pump_start < heater_start


def test_heater_program_is_not_exposed_as_duplicate_homekit_switch():
    switch = Path("custom_components/pentair_cloud/switch.py").read_text()

    assert 'entities.append(PentairRelaySwitch(_LOGGER, hub, device, "heater"' not in switch
    assert "update_pentair_devices_status" not in switch
