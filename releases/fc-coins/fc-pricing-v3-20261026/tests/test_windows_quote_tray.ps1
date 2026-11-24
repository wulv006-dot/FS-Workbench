$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../deploy/windows-quote-tray/QuoteTray.cs'
$compiler = "$env:WINDIR/Microsoft.NET/Framework64/v4.0.30319/csc.exe"
$temp = Join-Path ([IO.Path]::GetTempPath()) ('fs-quote-tray-test-' + [guid]::NewGuid())
$null = New-Item -ItemType Directory -Path $temp
try {
    $test = @'
using System;
using System.IO;
using System.Windows.Forms;
using FsQuoteTray;
static class Checks {
    static void Assert(bool result, string label) { if (!result) throw new Exception(label); }
    [STAThread] static int Main(string[] args) {
        var now = DateTimeOffset.Parse("2026-11-24T09:15:00+08:00");
        var id = Guid.NewGuid().ToString();
        string row = "{\"source\":\"U4GM\",\"platform\":\"PS\",\"purchase_k\":\"100\",\"currency\":\"USD\",\"run_id\":\""+id+"\",\"regular_price\":\"6.52\",\"captured_at\":\"2026-11-24T09:14:00+08:00\",\"conditional\":false,\"coupon_excluded\":true,\"comparable\":true,\"extra_bonus_tier\":false}";
        Func<string,string> response = r => "{\"source\":\"U4GM\",\"run_id\":\""+id+"\",\"offers\":["+r+"],\"errors\":[]}";
        var model = QuoteView.From(response(row),id,now);
        Assert(model.Count==1 && model.Price("PS","100")=="$6.52","real price");
        Assert(model.Price("PC","1000")=="\u2014","missing is blank");
        Assert(QuoteView.From(response(row+","+row),id,now).Count==0,"duplicate");
        Assert(QuoteView.From(response(row),id,now.AddMinutes(16)).Count==0,"expired");
        Assert(QuoteView.From(response(row.Replace("6.52","0")),id,now).Count==0,"zero price");
        Assert(QuoteView.From(response(row.Replace("\"extra_bonus_tier\":false","\"extra_bonus_tier\":true")),id,now).Count==0,"bonus tier");
        Assert(QuoteView.From(response(row),Guid.NewGuid().ToString(),now).Count==0,"wrong identity");
        var memory = new QuoteHistory();
        memory.Observe(model);
        var missing = QuoteView.From(response(""),id,now.AddMinutes(20));
        Assert(memory.Display(missing,"PS","100",now.AddMinutes(20)).Contains("$6.52"),"retain actual price");
        Assert(memory.Display(missing,"PS","100",now.AddMinutes(20)).Contains("\u8fc7\u671f"),"mark expired");
        Assert(!memory.Display(model,"PS","100",now).Contains("\u8fc7\u671f"),"fresh is distinct");
        Assert(missing.Count==0 && missing.Price("PS","100")=="\u2014","history outside current quotes");
        if(args.Length==1) {
            var live = LocalPrices.Read().GetAwaiter().GetResult();
            Application.EnableVisualStyles();
            using(var form = new PriceWindow()) {
                form.RefreshView(live,new QuoteHistory(),DateTimeOffset.Now,false);
                form.Show();
                Application.DoEvents();
                Assert(form.Visible && !form.TopMost, "normal window");
                Console.WriteLine("Visible: "+form.Text+" / "+live.State);
                form.Hide();
                Assert(!form.Visible, "hidden on demand");
            }
        }
        Console.WriteLine("PASS");return 0;
    }
}
'@
    $testPath = Join-Path $temp 'Checks.cs'
    [IO.File]::WriteAllText($testPath,$test,[Text.UTF8Encoding]::new($true))
    $exe = Join-Path $temp 'Checks.exe'
    & $compiler /nologo /codepage:65001 /main:Checks /target:exe "/out:$exe" /r:System.Windows.Forms.dll /r:System.Drawing.dll /r:System.Web.Extensions.dll /r:System.Net.Http.dll $source $testPath
    if ($LASTEXITCODE) { throw 'Tray tests did not compile' }
    if ($env:FS_TRAY_WINDOW_SMOKE -eq '1') { & $exe 'window' } else { & $exe }
    if ($LASTEXITCODE) { throw 'Tray regression failed' }
} finally {
    foreach ($artifact in @('Checks.cs','Checks.exe')) {
        $path = Join-Path $temp $artifact
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path }
    }
    Remove-Item -LiteralPath $temp
}
