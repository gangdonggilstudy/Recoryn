"""Power-event policy; capture never resumes without an explicit user action.

Control methods run on the serialized recording-control lane. Suspend notice is
best effort: Windows can suspend before device/writer acknowledgements finish.
https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmsuspend
"""

from __future__ import annotations

from recoryn.app.desktop import DesktopRecorder
from recoryn.domain import SessionState


class PowerCoordinator:
    def __init__(self, recorder: DesktopRecorder) -> None:
        self.recorder = recorder
        self.resume_required = False

    def suspend(self) -> bool:
        session = self.recorder.session_id
        if session is None:
            return False
        state = self.recorder.library.get_session(session).state
        if state is SessionState.RECORDING:
            # Set intent before attempting acknowledgements. Failure must not
            # leave an automatic-resume path enabled after the system wakes.
            self.resume_required = True
            self.recorder.pause(reason="SUSPEND")
            return True
        return False

    def resume(self) -> None:
        """Called only by the user's Resume action, opening a fresh core epoch."""
        self.recorder.resume()
        self.resume_required = False
