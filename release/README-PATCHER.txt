Virtual Families 1 Patcher - {VERSION}

This patcher was created with Claude AI (Claude Code) in collaboration with Lorsieab2.

Created by Lorsieab2. This is a passion project dedicated to improving the "Virtual Families" experience!
No copyright infringement intended! Please support the original game creators! :)

Vanilla Virtual Families saves are compatible with the modded version!

Run Launch_GUI.bat for the GUI, or use Apply_{VERSION}_Patcher.bat and enter
or drag the original Virtual Families.exe. This package does not ship a
prebuilt Windows shortcut because .lnk targets are path-specific and can break
after ZIP extraction.

The patcher validates that the selected folder is an official Virtual Families
1.01.00 install before it creates backups or writes any modded output. It then
refreshes or creates a clearly labeled modded game folder next to the vanilla
folder (or in your Games folder when the game is under Program Files), writes
a backup under the modded folder in .vf1_patch_backups, copies the vanilla
game, writes the patched "Virtual Families - Modded.exe", and installs the
patcher's files in "Virtual Families 1 Patcher Files".

Click Enable/Disable Patches after changing checkboxes. With the vanilla
folder selected, the modded folder is rebuilt from the vanilla install with
only the checked patches. With only a modded folder selected, the patcher
switches the patches in that folder in place: each patch is a line in
"Virtual Families 1 Patcher Files\settings.ini", so the executable is never
patched again. Payload files are read-only/copy-only during apply.

Each rebuild first saves a copy of the old modded folder (about 65 MB), by
default in a new timestamped folder under .vf1_patch_backups; if you set the
Backup folder field (or --backup-dir) to a folder that already exists -- one
picked with Browse always does -- each run writes a new timestamped folder
inside it; a path that does not exist yet is created and used as given. The
patcher never deletes these; delete older ones yourself to reclaim disk
space, keeping the newest if you may want to restore from it.

Dry Run / Validate Only validates that the patcher's working. It checks
whether the selected folder looks right, whether the EXE is the expected
official one, whether the patch fits it, and whether the payload files are
intact. It does not actually change or write files. If you do not choose a
custom log path, dry-run and pre-write failure logs are written next to
manifest.json so the vanilla game folder stays untouched.

See Transparency Log.txt for every file the patcher writes.
