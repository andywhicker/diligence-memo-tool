"""
Drive the real Microsoft Excel (in the background) to recalculate and check a workbook.

Why: openpyxl writes formulas but cannot calculate them. Excel itself is the only
fully reliable calculator for an Excel model, and it is already on this PC.

check(path)                  -> recalc, count formulas, list every cell showing an error; saves
                                 the file so the calculated values are stored in it.
evaluate(path, sets, gets)   -> temporarily set input cells (e.g. scenario), recalc, read cells.
                                 Does NOT save, so the file is unchanged.
"""

import json
import subprocess
import tempfile
from pathlib import Path

_PS = r"""
param([string]$JobFile)
$ErrorActionPreference = 'Stop'
$job = Get-Content $JobFile -Raw | ConvertFrom-Json
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false; $xl.DisplayAlerts = $false
$out = @{ formulas = 0; errors = @(); values = @{} }
try {
  $wb = $xl.Workbooks.Open($job.path)
  foreach ($s in $job.sets) { $wb.Worksheets.Item($s.sheet).Range($s.cell).Value2 = $s.value }
  if ($job.ops) { foreach ($op in $job.ops) { & ([scriptblock]::Create($op)) } }
  $xl.CalculateFull()
  foreach ($ws in $wb.Worksheets) {
    try { $out.formulas += $ws.UsedRange.SpecialCells(-4123).Count } catch {}
    try {
      $errs = $ws.UsedRange.SpecialCells(-4123, 16)
      foreach ($c in $errs.Cells) { $out.errors += ("{0}!{1} {2}" -f $ws.Name, $c.Address($false, $false), $c.Text) }
    } catch {}
  }
  foreach ($g in $job.gets) {
    $r = $wb.Worksheets.Item($g.sheet).Range($g.cell)
    $out.values["$($g.sheet)!$($g.cell)"] = @{ text = $r.Text; value = $r.Value2 }
  }
  if ($job.save) { $wb.Save() }
  $wb.Close($false)
} finally { $xl.Quit(); [System.Runtime.InteropServices.Marshal]::ReleaseComObject($xl) | Out-Null }
$out | ConvertTo-Json -Depth 5 -Compress
"""


def _run(job: dict, timeout=300) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ps1, jf = Path(tmp) / "excel_job.ps1", Path(tmp) / "job.json"
        ps1.write_text(_PS, encoding="utf-8")
        jf.write_text(json.dumps(job), encoding="utf-8")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                            "-File", str(ps1), "-JobFile", str(jf)],
                           capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"Excel automation failed: {r.stderr.strip()[:800]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _split(ref: str):
    sheet, c = ref.split("!")
    return sheet.strip("'"), c.replace("$", "")


def check(path, ops=None) -> dict:
    """Recalculate in Excel, return {'formulas': n, 'errors': [...]}, and save calculated values."""
    return _run({"path": str(Path(path).resolve()), "sets": [], "gets": [], "ops": ops or [], "save": True})


def evaluate(path, sets: dict, gets: list) -> dict:
    """sets: {'Assumptions!C5': 'Upside'}; gets: ['Assumptions!C40']. Returns {ref: {'text', 'value'}}."""
    job = {"path": str(Path(path).resolve()),
           "sets": [{"sheet": s, "cell": c, "value": v} for s, c, v in ((*_split(k), v) for k, v in sets.items())],
           "gets": [{"sheet": s, "cell": c} for s, c in (_split(g) for g in gets)],
           "ops": [], "save": False}
    return _run(job)
