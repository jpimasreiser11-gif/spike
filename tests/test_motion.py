"""Spike Motion (D): a scene plays on a virtual clock in an offline Chromium and ffmpeg encodes it. Frames land
where the animation says at each exact time, the same scene gives the same frames, nothing reaches the network,
and the tool, the chat and the CLI hand back a playable file."""

import asyncio
import hashlib
import io
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.motion import render as motion
from spike.motion.render import MotionError, Rendered, capture, render, scene_html
from spike.motion.tools import RenderVideo
from spike.server.app import create_app
from spike.server.state import AppState
from spike.tools.builtin import Workspace
from tests.helpers import ScriptedProvider, call, text

pytest.importorskip("playwright")
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is not installed")
Image = pytest.importorskip("PIL.Image")

@pytest.fixture(scope="module", autouse=True)
def chromium_available():
    async def probe():
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            await (await motion.launch(pw)).close()

    try:
        asyncio.run(probe())
    except MotionError as exc:
        pytest.skip(str(exc))


# A 2-second scene that moves the same distance four ways: CSS keyframes, SVG <animate>, a canvas drawn from the
# requestAnimationFrame timestamp, and a timer that changes the background at exactly 1 s.
SCENE = """<!doctype html><html><head><style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#052E1E}
.box{position:absolute;left:0;top:300px;width:100px;height:100px;background:#88D445;animation:move 2s linear forwards}
@keyframes move{to{transform:translateX(1180px)}}
</style></head><body><div class="box"></div>
<svg width="1280" height="720" style="position:absolute;inset:0"><circle cx="100" cy="100" r="40" fill="#E3FADA">
<animate attributeName="cx" from="100" to="1100" dur="2s" fill="freeze"/></circle></svg>
<canvas id="c" width="1280" height="100" style="position:absolute;left:0;top:600px"></canvas>
<script>
const ctx = document.getElementById("c").getContext("2d");
function loop(ts) { ctx.clearRect(0, 0, 1280, 100); ctx.fillStyle = "#FDFDFA";
  ctx.fillRect(Math.min(ts / 2000, 1) * 1180, 0, 100, 100); requestAnimationFrame(loop); }
requestAnimationFrame(loop);
setTimeout(() => { document.body.style.background = "#5FBB47"; }, 1000);
</script></body></html>"""


def frames_of(html, fps=30, seconds=None, size=(1280, 720)):
    shots: list[bytes] = []

    async def keep(png):
        shots.append(png)

    result = Rendered(path="", format="", codec="", width=size[0], height=size[1], fps=fps, seconds=0, frames=0)
    asyncio.run(capture(html, size[0], size[1], fps, seconds, keep, result))
    return shots, result


def left_edge(png: bytes, y: int, colour: tuple[int, int, int]) -> int:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    xs = [x for x in range(image.width) if all(abs(a - b) <= 3 for a, b in zip(image.getpixel((x, y)), colour, strict=True))]
    return xs[0] if xs else -1


def pixel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((x, y))


def probe(path: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                          "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    return {**data["streams"][0], "duration": float(data["format"]["duration"])}


def test_each_frame_is_the_scene_at_its_exact_time():
    shots, result = frames_of(SCENE)
    assert result.frames == 60 and result.seconds == 2 and result.duration_from == "animations"
    assert not result.errors and not result.blocked
    green, mint, cream = (0x88, 0xD4, 0x45), (0xE3, 0xFA, 0xDA), (0xFD, 0xFD, 0xFA)
    for frame, x in ((0, 0), (15, 295), (30, 590), (45, 885)):  # 1180 px in 2 s: 590 px per second
        assert abs(left_edge(shots[frame], 350, green) - x) <= 1, ("css", frame)
        assert abs(left_edge(shots[frame], 650, cream) - x) <= 1, ("canvas", frame)
        assert abs(left_edge(shots[frame], 100, mint) - (60 + x * 1000 / 1180)) <= 2, ("svg", frame)
    assert pixel(shots[29], 5, 5) == (0x05, 0x2E, 0x1E) and pixel(shots[30], 5, 5) == (0x5F, 0xBB, 0x47)  # timer


def test_the_same_scene_gives_the_same_frames():
    noisy = """<!doctype html><meta name="spike-duration" content="0.5"><body style="margin:0">
<canvas id="c" width="320" height="180"></canvas><p id="t"></p><script>
const ctx = document.getElementById("c").getContext("2d");
function loop() { ctx.fillStyle = `hsl(${Math.random() * 360} 80% 50%)`;
  ctx.fillRect(Math.random() * 300, Math.random() * 160, 20, 20); requestAnimationFrame(loop); }
requestAnimationFrame(loop);
setInterval(() => { document.getElementById("t").textContent = Date.now() + " " + performance.now(); }, 100);
</script>"""
    first, a = frames_of(noisy, fps=10, size=(320, 240))
    second, _ = frames_of(noisy, fps=10, size=(320, 240))
    assert a.frames == 5 and a.duration_from == "meta"
    assert [hashlib.sha256(f).hexdigest() for f in first] == [hashlib.sha256(f).hexdigest() for f in second]
    assert len({hashlib.sha256(f).hexdigest() for f in first}) == 5  # and it does change from frame to frame


def test_the_scene_runs_offline_and_its_errors_come_back():
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        html = f"""<!doctype html><meta name="spike-duration" content="0.2">
<link rel="stylesheet" href="{base}/style.css"><script src="{base}/lib.js"></script>
<img src="{base}/logo.png"><iframe src="{base}/frame"></iframe>
<script>fetch("{base}/fetch").catch(() => {{}}); try {{ new WebSocket("ws://127.0.0.1:{server.server_port}/ws"); }}
catch (e) {{}} navigator.sendBeacon && navigator.sendBeacon("{base}/beacon", "x"); window.open("{base}/popup");
alert("hola"); requestAnimationFrame(() => {{ throw new Error("boom en la escena"); }});</script>"""
        _, result = frames_of(html, fps=10, size=(320, 240))
    finally:
        server.shutdown()
    assert hits == []
    assert f"{base}/logo.png" in result.blocked and f"{base}/style.css" in result.blocked
    assert any("boom en la escena" in e for e in result.errors)


@pytest.mark.parametrize("html, seconds, expect", [
    ('<meta name="spike-duration" content="1.5">', None, (1.5, "meta")),
    ("<style>p{animation:a 1s 0.5s both}@keyframes a{to{opacity:0}}</style><p>x</p>", None, (1.5, "animations")),
    ("<style>p{animation:a 1s infinite}@keyframes a{to{opacity:0}}</style><p>x</p>", None, (5, "default")),
    ("<p>static</p>", None, (5, "default")),
    ('<meta name="spike-duration" content="9">', 0.5, (0.5, "argument")),
])
def test_the_length_comes_from_the_scene_or_the_call(html, seconds, expect):
    _, result = frames_of(html, fps=2, seconds=seconds, size=(160, 90))
    assert (result.seconds, result.duration_from) == expect and result.frames == round(expect[0] * 2)
    assert bool(result.notes) == (expect[1] == "default")


def test_formats_play_back_as_asked(tmp_path):
    clip = scene_html('<svg width="720" height="1280"><rect width="100" height="100" fill="#88D445">'
                      '<animate attributeName="x" from="0" to="600" dur="1s" fill="freeze"/></rect></svg>', ".svg")
    mp4 = asyncio.run(render(clip, tmp_path / "out" / "v.mp4", size="9:16", fps=24, seconds=1))
    info = probe(tmp_path / "out" / "v.mp4")
    assert (info["codec_name"], info["width"], info["height"], info["pix_fmt"], info["r_frame_rate"]) == (
        "h264", 720, 1280, "yuv420p", "24/1")
    assert int(info["nb_read_frames"]) == 24 and abs(info["duration"] - 1) < 0.05
    assert mp4.bytes == (tmp_path / "out" / "v.mp4").stat().st_size and not list((tmp_path / "out").glob(".*"))
    webm = asyncio.run(render(clip, tmp_path / "v.webm", size="320x240", fps=10, seconds=0.5))
    assert webm.codec == "vp9" and probe(tmp_path / "v.webm")["codec_name"] == "vp9"
    gif = asyncio.run(render(clip, tmp_path / "v.gif", size="1:1", fps=30, seconds=0.4))
    assert gif.fps == 15 and gif.frames == 6 and gif.notes == ["GIF at 15 fps"]
    assert Image.open(tmp_path / "v.gif").n_frames == 6


@pytest.mark.parametrize("kwargs, message", [
    ({"size": "4:3"}, "size must be"), ({"size": "1001x700"}, "even numbers"), ({"size": "4000x2000"}, "even numbers"),
    ({"fps": 0}, "fps must be"), ({"fps": 61}, "fps must be"), ({"fps": "30"}, "fps must be"),
    ({"seconds": 0}, "seconds must be"), ({"seconds": 61}, "seconds must be"),
])
def test_bad_settings_are_refused(tmp_path, kwargs, message):
    with pytest.raises(MotionError, match=message):
        asyncio.run(render("<p>x</p>", tmp_path / "v.mp4", **kwargs))


def test_bad_scenes_and_a_missing_ffmpeg_are_refused(tmp_path, monkeypatch):
    with pytest.raises(MotionError, match="must be .mp4"):
        asyncio.run(render("<p>x</p>", tmp_path / "v.mov"))
    with pytest.raises(MotionError, match="at most 60 s"):
        asyncio.run(render('<meta name="spike-duration" content="90">', tmp_path / "v.mp4", fps=1))
    with pytest.raises(MotionError, match="larger than 5 MB"):
        scene_html("x" * (motion.MAX_SCENE + 1), ".html")
    monkeypatch.setenv("SPIKE_FFMPEG", str(tmp_path / "nope"))
    with pytest.raises(MotionError, match="ffmpeg is not installed"):
        asyncio.run(render("<p>x</p>", tmp_path / "v.mp4"))


def test_the_tool_renders_a_scene_in_the_workspace(tmp_path):
    (tmp_path / "escenas").mkdir()
    (tmp_path / "escenas" / "intro.html").write_text(
        '<meta name="spike-duration" content="0.5"><style>body{margin:0;background:#052E1E}</style><h1>SPIKE</h1>'
        "<script>missing()</script>")
    (tmp_path / "logo.svg").write_text('<svg width="64" height="64"><circle cx="32" cy="32" r="20" fill="#88D445"/>'
                                       "</svg>")
    tool = RenderVideo(Workspace(tmp_path))
    args = {"scene": "escenas/intro.html", "output": "videos/intro.mp4", "size": "320x180", "fps": 10}
    assert tool.targets(args) == [tmp_path / "videos" / "intro.mp4"]
    done = asyncio.run(tool.run(args))
    assert done.ok and done.data["file"] == "videos/intro.mp4" and (tmp_path / "videos" / "intro.mp4").is_file()
    assert done.data["ui"] | {"bytes": 0} == {"kind": "video", "path": "videos/intro.mp4", "scene": "escenas/intro.html",
                                              "format": "mp4", "codec": "h264", "width": 320, "height": 180,
                                              "fps": 10, "seconds": 0.5, "frames": 5, "bytes": 0}
    assert "rendered videos/intro.mp4: 320x180, 10 fps, 0.5 s, 5 frames" in done.content
    assert "JavaScript errors" in done.content and "missing is not defined" in done.content
    svg = asyncio.run(tool.run({"scene": "logo.svg", "output": "logo.gif", "seconds": 0.2, "size": "1:1"}))
    assert svg.ok and svg.data["ui"]["format"] == "gif"
    for bad, message in ((dict(args, scene="../fuera.html"), "outside"), (dict(args, scene="nada.html"), "does not exist"),
                         (dict(args, scene="logo.png"), "must be .html"), (dict(args, output="v.avi"), "must be .mp4"),
                         (dict(args, fps="muchos"), "invalid literal")):
        result = asyncio.run(tool.run(bad))
        assert not result.ok and message in result.content, bad


@pytest.fixture
def app(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path), ("SPIKE_WORKSPACE", tmp_path / "ws"), ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    state.broker.policies.update({"write_file": "allow", "render_video": "allow"})
    client = TestClient(create_app(state))
    client.get("/api/providers")
    return client, local, tmp_path


def test_a_chat_writes_a_scene_renders_it_and_serves_a_playable_video(app):
    client, local, home = app
    scene = '<meta name="spike-duration" content="0.5"><body style="margin:0;background:#88D445"><h1>Hola</h1>'
    local._script = [call("write_file", {"path": "escena.html", "content": scene}),
                     call("render_video", {"scene": "escena.html", "output": "video.mp4", "size": "320x180",
                                           "fps": 10}, "c2"),
                     text("Listo: video.mp4, medio segundo.")]
    r = client.post("/api/chat", json={"message": "Hazme un vídeo animado corto que diga hola", "mode": "code"})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    video = [e for e in events if e["type"] == "tool_result" and e.get("ui", {}).get("kind") == "video"]
    assert len(video) == 1 and video[0]["ui"]["path"] == "video.mp4" and video[0]["ui"]["frames"] == 5
    assert "# Skill: motion-scene" in local.requests[0].messages[0].content
    assert "render_video" in {t.name for t in local.requests[0].tools}
    size = (home / "ws" / "video.mp4").stat().st_size
    whole = client.get("/api/workspace/files/video.mp4")
    assert whole.headers["content-type"] == "video/mp4" and whole.headers["content-security-policy"] == "sandbox"
    part = client.get("/api/workspace/files/video.mp4", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100 and part.headers["content-range"] == f"bytes 0-99/{size}"
    assert client.get("/api/workspace/files/escena.html").headers["content-type"] == "application/octet-stream"
    conv = events[0]["id"]
    stored = client.get(f"/api/conversations/{conv}").json()
    assert any(t.get("ui", {}).get("kind") == "video" for m in stored["messages"] for t in m["meta"].get("tools", []))


def test_the_cli_renders_a_scene(tmp_path, capsys):
    from spike.cli import main

    (tmp_path / "s.html").write_text('<meta name="spike-duration" content="0.3"><p>hola</p>')
    assert main(["render", str(tmp_path / "s.html"), "--size", "320x180", "--fps", "10"]) == 0
    assert (tmp_path / "s.mp4").is_file() and "320x180, 10 fps, 0.3 s, 3 frames, h264" in capsys.readouterr().out
    assert main(["render", str(tmp_path / "nada.html")]) == 1
    assert main(["render", str(tmp_path / "s.html"), "-o", str(tmp_path / "s.mov")]) == 1
