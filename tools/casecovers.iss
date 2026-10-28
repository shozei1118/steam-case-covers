; Windows installer for the one-file PyInstaller build. Build with tools/build_windows.ps1 -Installer.
#ifndef AppVersion
  #error AppVersion must be provided by the build script.
#endif

[Setup]
AppId={{4208C18D-7530-45A4-AD85-65017411C101}
AppName=Case Covers
AppVersion={#AppVersion}
AppVerName=Case Covers {#AppVersion}
AppPublisher=Case Covers
DefaultDirName={localappdata}\Programs\Case Covers
DisableDirPage=no
UsePreviousAppDir=yes
DefaultGroupName=Case Covers
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=CaseCovers-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\CaseCovers.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE

[Files]
Source: "..\dist\CaseCovers.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Case Covers"; Filename: "{app}\CaseCovers.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Case Covers"; Filename: "{app}\CaseCovers.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
