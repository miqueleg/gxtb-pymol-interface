#define AppName "PyMOL-gxTB Runner"
#define AppVersion "1.0.2"
#define AppPublisher "PyMOL-gxTB Runner contributors"
#ifndef BundleDir
#define BundleDir "..\build\PyMOL-gxTB-Runner"
#endif
#ifndef OutputDir
#define OutputDir "..\dist"
#endif

[Setup]
AppId={{B1D0D285-F753-4C55-91AF-05E40C67301C}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PyMOL-gxTB Runner
DefaultGroupName=PyMOL-gxTB Runner
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=PyMOL-gxTB-Runner-Windows-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile={#BundleDir}\LICENSES\REPOSITORY_LICENSE.txt
UninstallDisplayIcon={app}\launcher\Start-PyMOL-gxTB.cmd

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PyMOL-gxTB Runner"; Filename: "{app}\launcher\Start-PyMOL-gxTB.cmd"; WorkingDir: "{app}"
Name: "{group}\Health Check"; Filename: "{app}\launcher\health_check.cmd"; WorkingDir: "{app}"
Name: "{autodesktop}\PyMOL-gxTB Runner"; Filename: "{app}\launcher\Start-PyMOL-gxTB.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\launcher\health_check.cmd"; Description: "Run bundled environment health check"; Flags: postinstall skipifsilent
