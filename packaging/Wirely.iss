; Inno Setup script for the Wirely installer. build_exe.bat and the GitHub build run it automatically;
; or open it in Inno Setup and press Compile. Needs dist\Wirely (from PyInstaller) first.
; The version comes from the command line (ISCC /DAppVersion=1.5.4 /DAppRevision=1.5.4); these are fallbacks.
#ifndef AppVersion
  #define AppVersion "1.5.4"
#endif
#ifndef AppRevision
  #define AppRevision "1.5.4"
#endif
#define AppName "Wirely"

[Setup]
AppId={{9C2E7A41-3B5D-4F8E-A6C1-2D7B90E4F513}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Wirely
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\Wirely.exe
UninstallDisplayName={#AppName}
SetupIconFile=..\wirely\assets\wirely.ico
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Wirely-Setup-{#AppRevision}
; install for everyone, or just for you (no admin needed)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "assoc"; Description: "Open .wirely circuit files with Wirely"; GroupDescription: "Files:"

[InstallDelete]
; installing over an older version: clear out its libraries first, so no stale files are left behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Wirely\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\Wirely.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Wirely.exe"; Tasks: desktopicon

[Registry]
; .wirely circuits (and .spark, from before the name change)
Root: HKA; Subkey: "Software\Classes\.wirely"; ValueType: string; ValueName: ""; ValueData: "Wirely.Circuit"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.spark"; ValueType: string; ValueName: ""; ValueData: "Wirely.Circuit"; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Wirely.Circuit"; ValueType: string; ValueName: ""; ValueData: "Wirely circuit"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Wirely.Circuit\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\_internal\wirely\assets\wirely_doc.ico"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Wirely.Circuit\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Wirely.exe"" ""%1"""; Tasks: assoc

[Run]
Filename: "{app}\Wirely.exe"; Description: "Start Wirely now"; Flags: nowait postinstall skipifsilent
