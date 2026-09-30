#define AppName "Ducky Voice Optimizer"
#define AppVersion "1.3.0"
#define AppPublisher "Ducky Voice Optimizer"
#define AppExeName "ducky-voice-optimizer.exe"
#ifndef AppArch
  #define AppArch "x64"
#endif

[Setup]
AppId={{73E4A791-9242-49CB-9D16-D46CB5789465}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\Ducky Voice Optimizer
DefaultGroupName=Ducky Voice Optimizer
DisableProgramGroupPage=yes
LicenseFile=..\..\TERMS.txt
OutputDir=..\..\release
OutputBaseFilename=ducky-voice-optimizer-{#AppVersion}-windows-{#AppArch}-setup
SetupIconFile=..\..\assets\ducky-voice-optimizer.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
#if AppArch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\ducky-voice-optimizer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Ducky Voice Optimizer"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Ducky Voice Optimizer"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Ducky Voice Optimizer"; Flags: nowait postinstall skipifsilent
