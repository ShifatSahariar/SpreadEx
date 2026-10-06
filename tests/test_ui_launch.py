"""`spreadex ui` should just work: no --port, no duplicates, no stale links, any number of projects."""
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from spreadex.api import registry
from spreadex.api.server import TOKEN_FILE, project_token
from spreadex.core.config import Config, load_config

SRC = str(Path(__file__).resolve().parents[1] / "src")


# ---------------------------------------------------------------- ports

def test_a_projects_preferred_port_is_stable_and_in_range(tmp_path):
    p = registry.preferred_port(tmp_path / "a")
    assert p == registry.preferred_port(tmp_path / "a")
    assert registry.BASE_PORT <= p < registry.BASE_PORT + registry.PORT_SPAN


def test_different_projects_mostly_get_different_ports(tmp_path):
    ports = {registry.preferred_port(tmp_path / f"p{i}") for i in range(30)}
    assert len(ports) >= 15, ports


def test_candidates_start_at_the_preferred_port_cover_the_range_and_end_with_the_os_choice(tmp_path):
    c = registry.candidate_ports(tmp_path)
    assert c[0] == registry.preferred_port(tmp_path) and c[-1] == 0
    assert len(set(c[:-1])) == registry.PORT_SPAN


def test_a_port_the_user_names_is_the_only_candidate(tmp_path):
    assert registry.candidate_ports(tmp_path, 9999) == [9999]


# --------------------------------------------------------------- tokens

def test_a_token_is_stable_private_and_per_project(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    t = registry.token_for(a)
    assert t == registry.token_for(a) and t != registry.token_for(b)
    path = registry._token_path(a)
    assert (path.stat().st_mode & 0o777) == 0o600


def test_rotating_changes_the_token_and_remembering_never_overwrites(tmp_path):
    t = registry.token_for(tmp_path)
    assert registry.token_for(tmp_path, rotate=True) != t
    keep = registry.token_for(tmp_path)
    registry.remember_token(tmp_path, "something-else")
    assert registry.token_for(tmp_path) == keep


def test_an_unconfigured_folder_gets_a_stable_token_and_nothing_is_written_in_it(tmp_path):
    cfg = Config.unconfigured(tmp_path)
    assert project_token(cfg) == project_token(cfg)
    assert list(tmp_path.iterdir()) == []


def _configured(tmp_path):
    (tmp_path / "spreadex.yaml").write_text(
        f"sut:\n  command: [{json.dumps(sys.executable)}, -c, 'pass']\noracle: {{type: crash}}\n"
        "generators: []\ncorpus: {path: seeds}\n")
    (tmp_path / "seeds").mkdir()
    return load_config(tmp_path / "spreadex.yaml")


def test_a_configured_projects_own_token_file_wins_and_is_mirrored(tmp_path):
    cfg = _configured(tmp_path)
    (cfg.state_dir).mkdir()
    (cfg.state_dir / TOKEN_FILE).write_text("legacy-token")
    assert project_token(cfg) == "legacy-token"
    assert registry.token_for(tmp_path) == "legacy-token", "the two stores agree"


def test_becoming_configured_keeps_the_token_the_browser_already_holds(tmp_path):
    before = project_token(Config.unconfigured(tmp_path))
    assert project_token(_configured(tmp_path)) == before


def test_rotating_updates_both_stores(tmp_path):
    cfg = _configured(tmp_path)
    old = project_token(cfg)
    new = project_token(cfg, rotate=True)
    assert new != old and (cfg.state_dir / TOKEN_FILE).read_text().strip() == new == registry.token_for(tmp_path)


# ------------------------------------------------------------- registry

def _dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_dead_servers_are_pruned_and_live_ones_kept(tmp_path):
    registry.register(tmp_path / "gone", 8800, pid=_dead_pid())
    registry.register(tmp_path / "here", 8801, pid=os.getpid())
    roots = [s["root"] for s in registry.live_servers()]
    assert str((tmp_path / "here").resolve()) in roots and str((tmp_path / "gone").resolve()) not in roots
    assert str((tmp_path / "gone").resolve()) not in registry._read(), "pruned from the file too"


def test_unregistering_only_removes_your_own_entry(tmp_path):
    registry.register(tmp_path, 8800, pid=os.getpid())
    registry.unregister(tmp_path, pid=os.getpid() + 999999)
    assert registry.live_servers()
    registry.unregister(tmp_path, pid=os.getpid())
    assert not registry.live_servers()


def test_a_live_pid_on_a_port_nobody_serves_is_not_found(tmp_path):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    registry.register(tmp_path, port, pid=os.getpid())
    assert registry.find_live(tmp_path) is None, "a pid can be reused; ask the server who it is"


# -------------------------------------------------- real server processes

class Server:
    def __init__(self, cwd, *extra, home):
        env = {**os.environ, "SPREADEX_HOME": str(home), "PYTHONPATH": SRC}
        self.proc = subprocess.Popen(
            [sys.executable, "-c", "import sys; from spreadex.cli.main import main; sys.exit(main(sys.argv[1:]))",
             "ui", "--no-open", *extra], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.out, self.url = "", None
        deadline = time.time() + 15
        while time.time() < deadline and self.proc.poll() is None:
            line = self.proc.stdout.readline()
            self.out += line
            m = re.search(r"Workbench:\s+(http://\S+)", line)
            if m:
                self.url = m.group(1)
            if self.url and ("Nothing is written" in line or "Rotate the token" in line):
                break

    @property
    def port(self):
        return int(re.search(r":(\d+)/", self.url).group(1))

    @property
    def token(self):
        return self.url.split("token=")[1]

    def project_root(self):
        req = Request(self.url.split("/?")[0] + "/api/project", headers={"X-SpreadEx-Token": self.token})
        with urlopen(req, timeout=5) as r:
            return json.loads(r.read())["root"]

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


@pytest.fixture
def servers():
    started = []
    yield started
    for s in started:
        s.stop()


def _cli(cwd, *args, home):
    env = {**os.environ, "SPREADEX_HOME": str(home), "PYTHONPATH": SRC}
    return subprocess.run([sys.executable, "-c", "import sys; from spreadex.cli.main import main; sys.exit(main(sys.argv[1:]))", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def test_two_projects_run_at_once_each_on_its_own_port_without_any_flags(tmp_path, home, servers):
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir(); b.mkdir()
    sa = Server(a, home=home); servers.append(sa)
    sb = Server(b, home=home); servers.append(sb)
    assert sa.url and sb.url and sa.port != sb.port
    assert Path(sa.project_root()).resolve() == a.resolve() and Path(sb.project_root()).resolve() == b.resolve()


def test_a_busy_preferred_port_means_the_next_free_one_not_an_error(tmp_path, home, servers):
    proj = tmp_path / "p"; proj.mkdir()
    blocker = socket.socket(); blocker.bind(("127.0.0.1", registry.preferred_port(proj))); blocker.listen()
    try:
        s = Server(proj, home=home); servers.append(s)
        assert s.url and s.port != registry.preferred_port(proj)
        assert "was busy" in s.out
        assert Path(s.project_root()).resolve() == proj.resolve()
    finally:
        blocker.close()


def test_a_port_you_name_that_is_taken_is_reported_and_says_to_drop_the_flag(tmp_path, home):
    proj = tmp_path / "p"; proj.mkdir()
    blocker = socket.socket(); blocker.bind(("127.0.0.1", 0)); blocker.listen()
    try:
        r = _cli(proj, "ui", "--no-open", "--port", str(blocker.getsockname()[1]), home=home)
        assert r.returncode == 1 and "leave --port out" in r.stderr + r.stdout
    finally:
        blocker.close()


def test_running_it_twice_reopens_the_same_server_instead_of_starting_another(tmp_path, home, servers):
    proj = tmp_path / "p"; proj.mkdir()
    first = Server(proj, home=home); servers.append(first)
    second = _cli(proj, "ui", "--no-open", home=home)
    assert second.returncode == 0 and "already running" in second.stdout
    assert first.url.split("/?")[0] in second.stdout and first.token in second.stdout
    listing = _cli(proj, "ui", "--list", home=home).stdout
    assert listing.count(str(proj.resolve())) == 1


def test_a_restart_comes_back_on_the_same_address_with_the_same_token(tmp_path, home, servers):
    proj = tmp_path / "p"; proj.mkdir()
    first = Server(proj, home=home)
    url = first.url
    first.stop()
    time.sleep(0.5)
    second = Server(proj, home=home); servers.append(second)
    assert second.url == url, "bookmarks and open tabs must survive a restart"


def test_list_shows_every_running_project_and_stop_stops_only_this_one(tmp_path, home, servers):
    a, b = tmp_path / "alpha", tmp_path / "beta"
    a.mkdir(); b.mkdir()
    sa = Server(a, home=home); servers.append(sa)
    sb = Server(b, home=home); servers.append(sb)
    out = _cli(a, "ui", "--list", home=home).stdout
    assert str(a.resolve()) in out and str(b.resolve()) in out
    assert "Stopped" in _cli(a, "ui", "--stop", home=home).stdout
    time.sleep(1.0)
    out = _cli(a, "ui", "--list", home=home).stdout
    assert str(a.resolve()) not in out and str(b.resolve()) in out
    assert "No Workbench is running" in _cli(a, "ui", "--stop", home=home).stdout


def test_stopping_a_server_removes_it_from_the_list_and_leaves_the_project_untouched(tmp_path, home, servers):
    proj = tmp_path / "p"; proj.mkdir()
    s = Server(proj, home=home); servers.append(s)
    s.stop()
    time.sleep(0.5)
    assert "No Workbench is running" in _cli(proj, "ui", "--list", home=home).stdout
    assert list(proj.iterdir()) == [], "an unconfigured folder must leave no trace"


# ---------------------------------------------------------------- browser

STATIC = Path(SRC) / "spreadex" / "api" / "static"


def test_the_page_keeps_the_token_for_the_tab_and_for_the_address():
    js = (STATIC / "app.js").read_text()
    head = js[:js.index("async function api(path, body)")]
    assert "sessionStorage.getItem(k) || localStorage.getItem(k)" in head
    assert "sessionStorage.setItem(k, v); localStorage.setItem(k, v)" in head
    assert 'history.replaceState({}, "", incoming.pathname)' in head, "the token still leaves the address bar"


def test_the_recovery_card_points_at_spreadex_ui_and_no_longer_blames_a_restart():
    js = (STATIC / "app.js").read_text()
    card = js[js.index("function failureCard"):js.index("const esc = s =>")]
    assert "spreadex ui" in card and "restarted" not in card
