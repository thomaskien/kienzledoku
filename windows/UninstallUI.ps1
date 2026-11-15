function New-Button($Parent,$Text,$X,$Y,$Width){$b=New-Object Windows.Forms.Button;$b.Text=$Text;$b.SetBounds($X,$Y,$Width,40);$Parent.Controls.Add($b);return $b}
function New-Label($Parent,$Text,$X,$Y,$Width,$Height){$l=New-Object Windows.Forms.Label;$l.Text=$Text;$l.SetBounds($X,$Y,$Width,$Height);$Parent.Controls.Add($l);return $l}
function New-Page($Title,$Height){$f=New-Object Windows.Forms.Form;$f.Text=$Title;$f.ClientSize=New-Object Drawing.Size(720,$Height);$f.StartPosition='CenterScreen';$f.Font=New-Object Drawing.Font('Segoe UI',11);$f.BackColor=[Drawing.Color]::White;$f.AutoScaleMode='Dpi';return $f}
function Show-ProductCodeGuide {
 $guide=New-Page 'KienzleDoku in T2med aktivieren' 480
 $images=@();$y=20
 $steps=@(
  @{Text='1. Drittanbieter-Zugriffe verwalten: Per Produktcode aktivieren wählen.';File='t2med-produktcode-aktivieren.png'},
  @{Text='2. Produktcode kienzledoku eingeben und die Aktivierung bestätigen.';File='t2med-produktcode-kienzledoku.png'},
  @{Text='3. KienzleDoku erscheint mit einem grünen Statuspunkt.';File='t2med-kienzledoku-aktiv.png'}
 )
 try {
  foreach($step in $steps){
   $null=New-Label $guide $step.Text 25 $y 670 35;$y+=35
   $img=[Drawing.Image]::FromFile((Join-Path $PSScriptRoot ('docs/images/'+$step.File)));$images+=,$img
   $picture=New-Object Windows.Forms.PictureBox;$picture.Image=$img;$picture.SizeMode='Zoom'
   $height=[math]::Min(125,$img.Height);$picture.SetBounds(25,$y,670,$height);$guide.Controls.Add($picture);$y+=$height+15
  }
  $done=New-Button $guide 'Fenster schließen' 470 425 225;$done.DialogResult='OK'
  $null=$guide.ShowDialog()
 } finally {$guide.Dispose();foreach($img in $images){$img.Dispose()}}
}

. (Join-Path $PSScriptRoot 'SetupUninstall.ps1')
Show-KienzledokuUninstall
