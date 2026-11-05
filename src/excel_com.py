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
  # Files in OneDrive have AutoSave on by default; it would silently save test edits. Turn it off.
  try { $wb.AutoSaveOn = $false } catch {}
  foreach ($s in $job.sets) {
    # Always pass text, as if typed into the cell: Excel's COM layer caches the first value's type
    # and rejects a number after a string in the same run.
    $t = if ($s.value -is [string]) { $s.value } else { ([double]$s.value).ToString([Globalization.CultureInfo]::InvariantCulture) }
    $wb.Worksheets.Item($s.sheet).Range($s.cell).Formula = [string]$t
  }
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
    """
    Recalculate in Excel, return {'formulas': n, 'errors': [...]}, and save calculated values.
    Works on a temporary copy outside OneDrive, then copies the result back: Office can serve a
    stale cached version of OneDrive files, and AutoSave can interfere.
    """
    import shutil
    path = Path(path).resolve()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / path.name
        shutil.copy2(path, work)
        result = _run({"path": str(work), "sets": [], "gets": [], "ops": ops or [], "save": True})
        shutil.copy2(work, path)
    return result


def scrub(path) -> None:
    """
    Remove personal metadata Excel adds on save: the absolute folder path it saved from
    (contains the Windows user name) and the 'last modified by' Office account name.
    """
    import re
    import shutil
    import zipfile
    path = Path(path)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / path.name
        with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "xl/workbook.xml":
                    data = re.sub(rb"<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>\s*<x15ac:absPath[^>]*/>\s*"
                                  rb"</mc:Choice>\s*</mc:AlternateContent>", b"", data)
                    data = re.sub(rb"<x15ac:absPath[^>]*/>", b"", data)
                elif item.filename == "docProps/core.xml":
                    data = re.sub(rb"<cp:lastModifiedBy>[^<]*</cp:lastModifiedBy>",
                                  b"<cp:lastModifiedBy>diligence-memo-tool</cp:lastModifiedBy>", data)
                    data = re.sub(rb"<dc:creator>[^<]*</dc:creator>", b"<dc:creator>diligence-memo-tool</dc:creator>", data)
                zout.writestr(item, data)
        shutil.copy2(out, path)


def evaluate(path, sets: dict, gets: list) -> dict:
    """
    sets: {'Assumptions!C5': 'Upside'}; gets: ['Assumptions!C40']. Returns {ref: {'text', 'value'}}.
    Works on a temporary copy outside OneDrive, so the original file can never be changed
    (Excel AutoSave on OneDrive files would otherwise save the test inputs).
    """
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / Path(path).name
        shutil.copy2(path, copy)
        job = {"path": str(copy),
               "sets": [{"sheet": s, "cell": c, "value": v} for s, c, v in ((*_split(k), v) for k, v in sets.items())],
               "gets": [{"sheet": s, "cell": c} for s, c in (_split(g) for g in gets)],
               "ops": [], "save": False}
        return _run(job)
