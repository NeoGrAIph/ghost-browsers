import asyncio
import os
import sys
import types


class _DummyStream:
    def __init__(self, lines=None):
        self._lines = list(lines or [])

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""

    async def read(self):
        return b""


class _DummyProcess:
    def __init__(self, stdout_lines=None):
        self.stdout = _DummyStream(stdout_lines)
        self.stderr = _DummyStream()
        self.returncode = None

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def test_launch_browser_server_overrides_moz_disable_http3(monkeypatch):
    sys.modules["camoufox"] = types.ModuleType("camoufox")
    sys.modules["camoufox"].launch_options = lambda *, headless: {}

    pydantic_module = types.ModuleType("pydantic")

    class _BaseModel:
        pass

    def _field(*args, **kwargs):  # noqa: D401 - simple stub
        return kwargs.get("default", None)

    def _model_validator(*args, **kwargs):
        def decorator(func):
            return func

        return decorator

    pydantic_module.BaseModel = _BaseModel
    pydantic_module.Field = _field
    pydantic_module.model_validator = _model_validator
    sys.modules["pydantic"] = pydantic_module

    pydantic_settings_module = types.ModuleType("pydantic_settings")

    class _BaseSettings:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    pydantic_settings_module.BaseSettings = _BaseSettings
    pydantic_settings_module.SettingsConfigDict = dict
    sys.modules["pydantic_settings"] = pydantic_settings_module

    playwright_module = types.ModuleType("playwright")
    playwright_impl_module = types.ModuleType("playwright._impl")
    driver_module = types.ModuleType("playwright._impl._driver")
    driver_module.compute_driver_executable = lambda: ("node", "cli")
    playwright_impl_module._driver = driver_module
    playwright_module._impl = playwright_impl_module

    async_api_module = types.ModuleType("playwright.async_api")
    async_api_module.Playwright = type("Playwright", (), {})

    sys.modules["playwright"] = playwright_module
    sys.modules["playwright._impl"] = playwright_impl_module
    sys.modules["playwright._impl._driver"] = driver_module
    sys.modules["playwright.async_api"] = async_api_module

    from camoufox_runner import sessions
    from camoufox_runner.sessions import SessionManager

    class DummySettings:
        disable_http3 = True
        disable_webrtc = True
        disable_ipv6 = False
        vnc_display_min = 100
        vnc_display_max = 100
        vnc_port_min = 5900
        vnc_port_max = 5900
        vnc_ws_port_min = 6900
        vnc_ws_port_max = 6900
        prewarm_headless = 0
        prewarm_vnc = 0
        start_url_wait = "load"

    settings = DummySettings()
    manager = SessionManager(settings=settings, playwright=None)

    monkeypatch.setattr(
        sessions,
        "launch_options",
        lambda *, headless: {"env": {"MOZ_DISABLE_HTTP3": "0"}},
    )

    captured_config = {}

    def fake_write_launch_config(options):
        captured_config["config"] = options
        return "/tmp/fake-config.json"

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _DummyProcess(stdout_lines=[b"ws://example\n", b""])

    monkeypatch.setattr(sessions, "_write_launch_config", fake_write_launch_config)
    monkeypatch.setattr(sessions, "_remove_file", lambda path: None)
    monkeypatch.setattr(sessions.asyncio, "to_thread", immediate_to_thread)
    monkeypatch.setattr(sessions, "compute_driver_executable", lambda: ("node", "cli"))
    monkeypatch.setattr(
        sessions.aio_subprocess,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    async def run_test():
        server = await manager._launch_browser_server(headless=True, vnc=False, display=None)
        profile_dir = captured_config["config"]["userDataDir"]
        assert os.path.isdir(profile_dir)
        await server.close()

        config = captured_config["config"]
        assert config["env"]["MOZ_DISABLE_HTTP3"] == "1"
        assert config["persistentContext"] is True
        assert config["userDataDir"] == profile_dir
        prefs = config["firefoxUserPrefs"]
        assert prefs["network.http.http3.enabled"] is False
        assert prefs["network.http.http3.enable"] is False
        assert prefs["network.http.http3.enable_alt_svc"] is False
        assert prefs["network.http.http3.alt_svc"] is False
        assert prefs["network.dns.http3_echconfig.enabled"] is False
        assert prefs["network.dns.use_https_rr_as_altsvc"] is False
        assert prefs["network.http.altsvc.enabled"] is False
        assert prefs["network.http.altsvc.https"] is False
        assert prefs["media.peerconnection.enabled"] is False
        assert not os.path.exists(profile_dir)

    asyncio.run(run_test())


def test_disable_http3_drains_prewarmed(monkeypatch):
    from camoufox_runner.sessions import SessionManager

    class DummySettings:
        disable_http3 = False
        disable_webrtc = True
        disable_ipv6 = False
        vnc_display_min = 100
        vnc_display_max = 100
        vnc_port_min = 5900
        vnc_port_max = 5900
        vnc_ws_port_min = 6900
        vnc_ws_port_max = 6900
        prewarm_headless = 0
        prewarm_vnc = 0
        start_url_wait = "load"

    settings = DummySettings()
    manager = SessionManager(settings=settings, playwright=None)

    drained = False

    async def fake_close_prewarmed(self):
        nonlocal drained
        drained = True

    monkeypatch.setattr(SessionManager, "_close_prewarmed", fake_close_prewarmed)

    asyncio.run(manager.disable_http3())

    assert settings.disable_http3 is True
    assert drained is True
