; Instalador de Frameguard (Inno Setup 6). Se compila con build.ps1:
;   ISCC /DAppVersion=0.1.0 installer\frameguard.iss
; El AppId NO debe cambiar nunca: es lo que hace que una versión nueva se instale ENCIMA de la anterior.

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8F3C2A51-6D0E-4B7A-9C1E-5A1F0B2C3D4E}
AppName=Frameguard
AppVersion={#AppVersion}
AppVerName=Frameguard {#AppVersion}
AppPublisher=Frameguard
AppComments=Render queue manager for Blender
VersionInfoVersion={#AppVersion}
VersionInfoDescription=Frameguard Setup
SourceDir=..
OutputDir=dist\installer
OutputBaseFilename=Frameguard-Setup-{#AppVersion}
SetupIconFile=assets\frameguard.ico
UninstallDisplayIcon={app}\Frameguard.exe
UninstallDisplayName=Frameguard
DefaultDirName={autopf}\Frameguard
DisableDirPage=auto
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
; Por usuario y sin pedir administrador (sirve en PCs sin permisos de administrador); se puede elegir "para todos".
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=force
RestartApplications=no
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Idioma: el de Windows. Español si Windows está en español; si no, inglés (el primero de la lista).
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
spanish.DesktopIcon=Crear un acceso directo en el escritorio
english.Shortcuts=Shortcuts:
spanish.Shortcuts=Accesos directos:
english.OpenApp=Open Frameguard
spanish.OpenApp=Abrir Frameguard
english.QueueFile=Frameguard queue
spanish.QueueFile=Cola de Frameguard
english.RenderingNow=Frameguard is rendering right now.%n%nIf you continue, the render will be interrupted. When you open Frameguard again it will resume from the last verified frame.%n%nInstall anyway?
spanish.RenderingNow=Frameguard está renderizando ahora mismo.%n%nSi continúas, el render se interrumpirá. Al volver a abrir Frameguard se reanudará desde el último frame verificado.%n%n¿Instalar de todos modos?

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:Shortcuts}"

[InstallDelete]
; Limpia los archivos del programa de la versión anterior (los datos del usuario están en %APPDATA%\Frameguard)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Frameguard\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Doble clic en una cola guardada (.fgq) abre Frameguard
Root: HKA; Subkey: "Software\Classes\.fgq"; ValueType: string; ValueName: ""; ValueData: "Frameguard.Cola"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Frameguard.Cola"; ValueType: string; ValueName: ""; ValueData: "{cm:QueueFile}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Frameguard.Cola\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\Frameguard.exe,0"
Root: HKA; Subkey: "Software\Classes\Frameguard.Cola\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Frameguard.exe"" ""%1"""

[Icons]
Name: "{autoprograms}\Frameguard"; Filename: "{app}\Frameguard.exe"
Name: "{autodesktop}\Frameguard"; Filename: "{app}\Frameguard.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Frameguard.exe"; Description: "{cm:OpenApp}"; Flags: nowait postinstall skipifsilent
; Tras una actualización silenciosa desde el propio programa, se vuelve a abrir solo
Filename: "{app}\Frameguard.exe"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM Frameguard.exe /F"; Flags: runhidden; RunOnceId: "CerrarFrameguard"

[Code]
function InitializeSetup(): Boolean;
var
  Lock: String;
begin
  Result := True;
  { El motor mantiene este archivo mientras la cola trabaja: no interrumpir un render sin preguntar }
  Lock := ExpandConstant('{userappdata}\Frameguard\runtime\rendering.lock');
  if FileExists(Lock) then
    Result := SuppressibleMsgBox(CustomMessage('RenderingNow'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { Cierra Frameguard (ventana y motor) para poder reemplazar sus archivos. El motor no tiene ventana y no
    se puede cerrar "con cortesía". Si estaba renderizando, el usuario ya lo aceptó en InitializeSetup y el
    render se reanudará desde el último frame verificado. }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM Frameguard.exe /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(800);
  Result := '';
end;
