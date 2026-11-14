# PyInstaller 6.22.3: shared onedir binaries; no embedded model weights.
import json
import os
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from release_manager import WEIGHTS, safe

root = Path(SPECPATH).parent
datas = []
binaries = []
hidden = collect_submodules('recoryn') + collect_submodules('faster_whisper')
hidden += ['release_manager', 'release_smoke', 'onnxruntime', 'tokenizers',
           'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'PySide6.QtMultimedia']
for name in ('faster_whisper', 'ctranslate2', 'onnxruntime', 'tokenizers'):
    datas += collect_data_files(name)
    binaries += collect_dynamic_libs(name)
for package, module, pin in (
    ('onnx', 'onnx', '1.23.2'),
    ('sherpa-onnx', 'sherpa_onnx', '2.0.1'),
    ('sherpa-onnx-core', 'sherpa_onnx', '2.0.1'),
    ('numpy', 'numpy', '2.3.5'),
):
    try:
        installed = distribution(package)
    except PackageNotFoundError:
        # A source-only/minimal environment has no such capability. The final
        # Python 3.13 builder requires all pins before invoking this spec.
        continue
    if installed.version != pin:
        raise ValueError('DIARIZATION_DEPENDENCY_VERSION_MISMATCH')
    hidden += [module]
    datas += collect_data_files(module)
    binaries += collect_dynamic_libs(module)
    # Keep metadata for capabilities() inside the frozen distribution. Discover
    # the actual dist-info directory through RECORD, never copy Scripts tools.
    for entry in installed.files or []:
        if entry.name == 'METADATA' and entry.parent.name.endswith('.dist-info'):
            source = safe(Path(os.path.abspath(installed.locate_file(entry.parent))))
            datas.append((str(source), entry.parent.name))
hidden += ['onnx.onnx_cpp2py_export', 'sherpa_onnx.lib._sherpa_onnx']
datas = [(source, dest) for source, dest in datas
         if Path(source).suffix.lower() not in WEIGHTS]

common = dict(pathex=[str(root / 'src'), str(root / 'packaging')], binaries=binaries,
              datas=datas, hiddenimports=hidden, hookspath=[], runtime_hooks=[],
              excludes=['PyQt5', 'PyQt6', 'PySide2', 'torch', 'tensorflow', 'pytest', 'IPython'],
              noarchive=False)
gui = Analysis([str(root / 'packaging' / 'entry_gui.py')], **common)
cli = Analysis([str(root / 'packaging' / 'entry_cli.py')], **common)

# Hooks can add data after the initial collection filter. Refuse a candidate
# containing any weights, including optional VAD models, before making EXEs.
for analysis in (gui, cli):
    if any(Path(row[0]).suffix.lower() in WEIGHTS
           for row in list(analysis.datas) + list(analysis.binaries)):
        raise ValueError('BUNDLED_MODEL_WEIGHTS_FORBIDDEN')

evidence = Path(os.environ['RECORYN_BUILD_EVIDENCE'])
evidence.write_text(json.dumps({'pure': list(gui.pure) + list(cli.pure),
                              'binaries': list(gui.binaries) + list(cli.binaries),
                              'datas': list(gui.datas) + list(cli.datas)}, sort_keys=True), encoding='utf-8')
gui_exe = EXE(PYZ(gui.pure), gui.scripts, [], exclude_binaries=True, name='Recoryn',
              console=False, debug=False, strip=False, upx=False, disable_windowed_traceback=False)
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name='Recoryn-CLI',
              console=True, debug=False, strip=False, upx=False)
bundle = COLLECT(gui_exe, cli_exe, gui.binaries, cli.binaries, gui.datas, cli.datas,
                 strip=False, upx=False, name='Recoryn')
