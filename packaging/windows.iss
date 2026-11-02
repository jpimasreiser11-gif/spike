#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef Version
  #error Version is required
#endif
[Setup]
AppId={{D564DAD2-2552-45E8-A187-1953FD54539D}
AppName=SPIKE
AppVersion={#Version}
AppPublisher=SPIKE
DefaultDirName={localappdata}\Programs\SPIKE
DefaultGroupName=SPIKE
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=SPIKE-{#Version}-Windows-AMD64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SPIKE.exe
CloseApplications=yes
RestartApplications=no
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\SPIKE"; Filename: "{app}\SPIKE.exe"
[Run]
Filename: "{app}\SPIKE.exe"; Description: "Abrir SPIKE / Open SPIKE"; Flags: nowait postinstall skipifsilent
