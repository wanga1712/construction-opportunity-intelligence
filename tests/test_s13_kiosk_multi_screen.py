import base64
import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ENTRYPOINT = ROOT / "deploy" / "s13_dashboard3.py"
SPEC = importlib.util.spec_from_file_location("s13_dashboard3_multiscreen", ENTRYPOINT)
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)
PAGE = dashboard.PAGE
SCRIPTS = re.findall(r"<script>(.*?)</script>", PAGE, re.S)


def _controller_assertions(body):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the kiosk rotation contract")
    source = base64.b64encode(SCRIPTS[0].encode("utf-8")).decode("ascii")
    harness = r"""
const vm=require('node:vm'),assert=require('node:assert/strict');
const window={};
vm.runInNewContext(Buffer.from(process.argv[1],'base64').toString('utf8'),{window,Date});
let clock=0,next=0,jobs=new Map(),changes=[];
const timers={setTimeout(fn,ms){const id=++next;jobs.set(id,{at:clock+ms,fn});return id},clearTimeout(id){jobs.delete(id)}};
function advance(ms){const end=clock+ms;while(true){let found=null;for(const [id,j] of jobs){if(j.at<=end&&(!found||j.at<found.j.at))found={id,j}}if(!found)break;jobs.delete(found.id);clock=found.j.at;found.j.fn()}clock=end}
const c=window.createScreenController((screen,manual)=>changes.push({at:clock,screen,manual}),()=>clock,timers);c.start();
""" + body
    result = subprocess.run(
        [node, "-e", harness, source], text=True, encoding="utf-8", capture_output=True
    )
    assert result.returncode == 0, result.stderr


def test_three_primary_screens_exist():
    assert PAGE.count('data-screen="NOW"') == 1
    assert PAGE.count('data-screen="RESOURCES"') == 1
    assert PAGE.count('data-screen="COMMERCIAL"') == 1


def test_now_screen_contains_single_today_pipeline():
    assert PAGE.count('id="todayPipeline"') == 1
    assert "today_truth" in PAGE and "c.accepted" in PAGE
    assert "needs_research" in PAGE and "ready_cards" in PAGE


def test_resources_screen_contains_all_cpu_cores():
    assert "Array.isArray(c.per)?c.per:[]" in PAGE
    assert "p.map(function(v,i)" in PAGE
    assert "cpu_package_temp_c" not in PAGE  # API contract uses existing temperature bundle keys.
    assert "t.package" in PAGE and "t.core_max" in PAGE


def test_commercial_screen_contains_commercial_totals():
    assert "live_total" in PAGE
    assert "c.open" in PAGE and "c.awarded" in PAGE
    assert "GOLD" in PAGE and "SILVER" in PAGE and "BRONZE" in PAGE and "WOOD" in PAGE


def test_auto_rotation_sequence():
    _controller_assertions(
        "advance(20000);advance(15000);advance(20000);advance(15000);"
        "assert.deepEqual(changes.filter(x=>!x.manual).map(x=>x.screen),"
        "['NOW','RESOURCES','NOW','COMMERCIAL','NOW']);"
    )


def test_manual_screen_switch():
    _controller_assertions(
        "assert.equal(c.select('COMMERCIAL'),true);"
        "assert.equal(c.state().screen,'COMMERCIAL');"
        "assert.equal(c.select('INVALID'),false);"
    )


def test_manual_switch_pauses_rotation():
    _controller_assertions(
        "c.select('RESOURCES');advance(29999);"
        "assert.equal(c.state().screen,'RESOURCES');advance(1);"
        "assert.equal(c.state().screen,'NOW');"
        "assert.equal(changes.at(-1).at,30000);"
    )


def test_critical_returns_to_now():
    _controller_assertions(
        "c.setCritical(true);assert.equal(c.state().screen,'NOW');"
        "c.select('COMMERCIAL');advance(30000);"
        "assert.equal(c.state().screen,'NOW');"
    )


def test_missing_temp_renders_na():
    assert "temp=function(v)" in PAGE
    assert "v===null||v===undefined||!isFinite(Number(v))?L.na" in PAGE


def test_missing_gpu_metric_renders_na():
    assert "pct=function(v)" in PAGE
    assert "pct(g.util)" in PAGE
    assert "v===null||v===undefined||!isFinite(Number(v))?L.na" in PAGE


def test_no_primary_screen_horizontal_scroll_contract():
    assert "html,body{direction:ltr!important;margin:0;width:100%;height:100%;overflow:hidden" in PAGE
    assert "main{min-width:0;min-height:0;overflow:hidden" in PAGE


def test_no_vertical_scroll_now_contract():
    assert "#screen-now{" in PAGE and "overflow:hidden" in PAGE


def test_no_vertical_scroll_resources_contract():
    assert "#screen-resources{" in PAGE and "overflow:hidden" in PAGE


def test_no_vertical_scroll_commercial_contract():
    assert "#screen-commercial{" in PAGE and "overflow:hidden" in PAGE


def test_no_duplicate_today_pipeline():
    assert PAGE.count('id="todayPipeline"') == 1


def test_initial_signal_absent_from_main_pipeline():
    assert "INITIAL SIGNAL" not in PAGE


def test_classified_absent_from_main_pipeline():
    assert "CLASSIFIED" not in PAGE



def test_all_inline_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for inline JavaScript syntax validation")
    source = "\n".join(SCRIPTS)
    result = subprocess.run([node, "--check", "-"], input=source, text=True, encoding="utf-8", capture_output=True)
    assert result.returncode == 0, result.stderr


def test_active_procurement_requires_live_assessment_pid():
    assert "a.state==='active'||a.state==='activating'" in PAGE
    assert "Number(a.pid)>0" in PAGE
    assert "a.procurement_id" in PAGE


def test_navigation_labels_initialized_before_display():
    assert "txt('navNow',L.now)" in PAGE
    assert "txt('navResources',L.resources)" in PAGE
    assert "txt('navCommercial',L.commercial)" in PAGE
    assert "txt('brand',L.brand)" in PAGE


def test_hardware_line_renders_safe_formatted_markup():
    assert "$('hardwareLine').innerHTML='CPU <strong>'+esc(pct" in PAGE
    assert '<html lang="ru" dir="ltr">' in PAGE
    assert "setAttribute('dir','ltr')" in PAGE


def test_http_page_responses_disable_stale_kiosk_cache():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'self.send_header("Cache-Control","no-store, no-cache, must-revalidate")' in source
    assert 'self.send_header("Expires","0")' in source


def test_inactive_resource_screen_can_be_hidden():
    assert '#screen-resources{direction:ltr!important;' in PAGE
    assert 'data-screen="RESOURCES"' in PAGE
    assert 'display:block!important' not in PAGE



def test_primary_layout_uses_normal_flow_and_one_active_screen():
    assert "*{direction:ltr!important;unicode-bidi:normal!important}" in PAGE
    assert "#screen-resources .res-group{position:static" in PAGE
    assert "#screen-now .flow{position:relative;display:grid" in PAGE
    assert "position:absolute;left:'+p[0]" not in PAGE
