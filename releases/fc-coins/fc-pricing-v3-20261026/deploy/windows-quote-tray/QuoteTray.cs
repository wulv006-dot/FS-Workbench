using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Linq;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

namespace FsQuoteTray {
    public class Offer {
        public string source, platform, purchase_k, regular_price, currency, captured_at, run_id;
        public bool? conditional, coupon_excluded, comparable, extra_bonus_tier;
    }
    public class Receipt {
        public string source, run_id;
        public Offer[] offers;
        public string[] errors;
    }
    public class Health { public bool ok; }
    public class DisplayPrice { public string Text; public DateTimeOffset Captured; }

    public class QuoteView {
        public static readonly string[] Platforms = {"PS","XBOX","PC"};
        public static readonly string[] Sizes = {"100","1000"};
        internal readonly Dictionary<string,DisplayPrice> Prices = new Dictionary<string,DisplayPrice>();
        public int Count { get { return Prices.Count; } }
        public string State = "等待读取";
        public DateTimeOffset? Latest;
        public string Price(string platform,string size) {
            DisplayPrice price;
            return Prices.TryGetValue(platform + "/" + size,out price) ? price.Text : "—";
        }
        public static QuoteView From(string json,string id,DateTimeOffset now) {
            var view = new QuoteView();
            var reply = new JavaScriptSerializer().Deserialize<Receipt>(json);
            if (reply == null || reply.source != "U4GM" || reply.run_id != id || reply.offers == null) {
                view.State = "报价响应无效"; return view;
            }
            foreach (var group in reply.offers.Where(o => o != null).GroupBy(o => o.platform + "/" + o.purchase_k)) {
                var o = group.First();
                DateTimeOffset time; decimal price;
                if (group.Count() != 1 || o.source != "U4GM" || o.run_id != id ||
                    !Platforms.Contains(o.platform) || !Sizes.Contains(o.purchase_k) ||
                    o.currency != "USD" || o.conditional != false || o.coupon_excluded != true ||
                    o.comparable != true || o.extra_bonus_tier == true ||
                    !decimal.TryParse(o.regular_price,NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out price) || price <= 0 ||
                    !DateTimeOffset.TryParse(o.captured_at,CultureInfo.InvariantCulture,DateTimeStyles.None,out time) ||
                    time > now || now-time > TimeSpan.FromMinutes(15)) continue;
                view.Prices.Add(group.Key,new DisplayPrice { Text="$" + price.ToString("0.00",CultureInfo.InvariantCulture), Captured=time });
                if (view.Latest == null || time > view.Latest) view.Latest = time;
            }
            var errors = reply.errors ?? new string[0];
            if (view.Count != 0) view.State = view.Count + " / 6 档有报价";
            else if (errors.Any(e => new[]{"source_blocked","http_401","http_403","http_429","challenge"}.Contains(e))) view.State = "来源限制访问";
            else if (errors.Contains("browser_snapshot_stale")) view.State = "报价已过期";
            else view.State = "暂无有效报价";
            return view;
        }
    }

    public class QuoteHistory {
        readonly Dictionary<string,DisplayPrice> last = new Dictionary<string,DisplayPrice>();
        public void Observe(QuoteView view) {
            foreach(var item in view.Prices) {
                DisplayPrice previous;
                if(!last.TryGetValue(item.Key,out previous) || item.Value.Captured>=previous.Captured) last[item.Key]=item.Value;
            }
        }
        public string Display(QuoteView view,string platform,string size,DateTimeOffset now) {
            string key=platform+"/"+size;
            DisplayPrice price;
            if(view.Prices.TryGetValue(key,out price) && now-price.Captured<=TimeSpan.FromMinutes(15)) return price.Text;
            if(!last.TryGetValue(key,out price)) return "—";
            string stamp=price.Captured.ToLocalTime().ToString(price.Captured.LocalDateTime.Date==now.LocalDateTime.Date?"HH:mm":"MM/dd HH:mm");
            return price.Text+"\n上次 "+stamp+(now-price.Captured>TimeSpan.FromMinutes(15)?" 过期":"");
        }
    }

    public static class LocalPrices {
        static readonly HttpClient Client = new HttpClient(new HttpClientHandler {UseProxy=false,AllowAutoRedirect=false}) {
            BaseAddress = new Uri("http://127.0.0.1:8790/"), Timeout=TimeSpan.FromSeconds(3),MaxResponseContentBufferSize=65536
        };
        public static async Task<QuoteView> Read() {
            var serializer = new JavaScriptSerializer();
            var id = Guid.NewGuid().ToString();
            try {
                var health = serializer.Deserialize<Health>(await Client.GetStringAsync("health"));
                if (health == null || !health.ok) return new QuoteView {State="本机服务不可用"};
                var wanted = from platform in QuoteView.Platforms from size in QuoteView.Sizes select new[]{platform,size};
                var payload = serializer.Serialize(new {source="U4GM",run_id=id,wanted=wanted.ToArray()});
                using (var content = new StringContent(payload,Encoding.UTF8)) {
                    content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");
                    using (var response = await Client.PostAsync("fc27-observation",content)) {
                        if (!response.IsSuccessStatusCode) return new QuoteView {State="本机报价接口不可用"};
                        return QuoteView.From(await response.Content.ReadAsStringAsync(),id,DateTimeOffset.Now);
                    }
                }
            } catch (HttpRequestException) { return new QuoteView {State="本机服务离线"}; }
              catch (TaskCanceledException) { return new QuoteView {State="本机服务超时"}; }
              catch (ArgumentException) { return new QuoteView {State="报价响应无效"}; }
              catch (InvalidOperationException) { return new QuoteView {State="报价响应无效"}; }
        }
    }

    public class PriceWindow : Form {
        readonly TableLayoutPanel layout;
        readonly Label status, time;
        readonly Label[,] cells = new Label[3,2];
        readonly List<Label> secondary = new List<Label>();
        public PriceWindow() {
            Text="FC27 本机报价";
            AutoScaleMode=AutoScaleMode.Dpi; StartPosition=FormStartPosition.CenterScreen;
            FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false; MinimizeBox=false;
            ClientSize=new Size(370,315); ShowInTaskbar=true;
            Font=new Font("Microsoft YaHei UI",9F);
            layout=new TableLayoutPanel { Dock=DockStyle.Fill, Padding=new Padding(16,10,16,10), ColumnCount=3, RowCount=8 };
            Controls.Add(layout);
            foreach (int w in new[]{34,33,33}) layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,w));
            foreach (int h in new[]{40,23,26,44,44,44,26,25}) layout.RowStyles.Add(new RowStyle(SizeType.Percent,h));
            Add("U4GM 普通购买价",0,0,3,true);
            status=Add("",0,1,3);
            Add("平台",0,2,1,false,true); Add("100K",1,2,1,false,true); Add("1000K",2,2,1,false,true);
            for (int r=0;r<3;r++) {
                Add(QuoteView.Platforms[r]=="XBOX" ? "Xbox" : QuoteView.Platforms[r],0,r+3,1);
                for(int c=0;c<2;c++) cells[r,c]=Add("—",c+1,r+3,1);
            }
            time=Add("",0,6,3,false,true);
            Add("USD   上次采价超过 15 分钟标为过期",0,7,3,false,true);
        }
        Label Add(string text,int column,int row,int span,bool title=false,bool muted=false) {
            var label = new Label { Text=text, Dock=DockStyle.Fill, TextAlign=ContentAlignment.MiddleLeft, Margin=Padding.Empty };
            if(title) label.Font=new Font(Font.FontFamily,14F,FontStyle.Bold);
            if(muted) secondary.Add(label);
            layout.Controls.Add(label,column,row); layout.SetColumnSpan(label,span); return label;
        }
        public void RefreshView(QuoteView view,QuoteHistory history,DateTimeOffset checkedAt,bool dark) {
            var normal=ColorTranslator.FromHtml(dark?"#e8eef6":"#1b2632");
            BackColor=ColorTranslator.FromHtml(dark?"#182641":"#ffffff");
            ForeColor=normal;
            foreach (var l in secondary) l.ForeColor=ColorTranslator.FromHtml(dark?"#b6c4d7":"#596980");
            status.ForeColor=ColorTranslator.FromHtml(view.Count>0 ? (dark?"#70cfa7":"#1f7d61") : (dark?"#f0c478":"#825a13"));
            status.Text=view.State;
            for(int r=0;r<3;r++) for(int c=0;c<2;c++) cells[r,c].Text=history.Display(view,QuoteView.Platforms[r],QuoteView.Sizes[c],DateTimeOffset.Now);
            time.Text="读取 "+checkedAt.ToLocalTime().ToString("HH:mm:ss")+
                (view.Latest.HasValue?"     最新采价 "+view.Latest.Value.ToLocalTime().ToString("HH:mm:ss"):"");
        }
    }

    class Tray : ApplicationContext {
        [DllImport("user32.dll")] static extern bool DestroyIcon(IntPtr icon);
        readonly NotifyIcon tray;
        readonly Icon waiting=Badge(Color.FromArgb(209,160,61)), fresh=Badge(Color.FromArgb(70,199,156));
        readonly System.Windows.Forms.Timer timer=new System.Windows.Forms.Timer {Interval=60000};
        PriceWindow window;
        readonly QuoteHistory history=new QuoteHistory();
        QuoteView view=new QuoteView();
        DateTimeOffset checkedAt=DateTimeOffset.Now;
        bool reading,stopped;
        public Tray() {
            var menu=new ContextMenuStrip();
            menu.Items.Add("查看报价",null,(s,e)=>ShowWindow());
            menu.Items.Add("退出",null,(s,e)=>ExitThread());
            tray=new NotifyIcon {Visible=true,Icon=waiting,Text="FC27 本机报价",ContextMenuStrip=menu};
            tray.MouseClick+=(s,e)=>{if(e.Button==MouseButtons.Left) ShowWindow();};
            timer.Tick+=(s,e)=>Poll();
            timer.Start(); Poll();
        }
        static Icon Badge(Color dot) {
            using (var bmp=new Bitmap(32,32))
            using (var g=Graphics.FromImage(bmp))
            using (var brush=new SolidBrush(dot)) {
                g.SmoothingMode=System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.FillEllipse(Brushes.Teal,1,1,29,29);
                using(var pen=new Pen(Color.White,3F)) { g.DrawLines(pen,new[]{new Point(8,21),new Point(8,9),new Point(19,9)});g.DrawLine(pen,8,15,16,15); }
                g.FillEllipse(brush,19,19,12,12);
                var handle=bmp.GetHicon();
                try { using(var icon=Icon.FromHandle(handle)) return (Icon)icon.Clone(); }
                finally { DestroyIcon(handle); }
            }
        }
        static bool Dark() { return Convert.ToInt32(Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize","AppsUseLightTheme",1))==0; }
        void ShowWindow() {
            if(window==null || window.IsDisposed) window=new PriceWindow();
            window.RefreshView(view,history,checkedAt,Dark());
            window.Show(); window.Activate(); Poll();
        }
        async void Poll() {
            if(reading || stopped) return;
            reading=true;
            try {
                var update=await LocalPrices.Read();
                if(stopped) return;
                view=update; history.Observe(view); checkedAt=DateTimeOffset.Now;
                tray.Icon=view.Count==0?waiting:fresh;
                tray.Text="FC27  ·  "+view.State+"  ·  "+checkedAt.ToString("HH:mm");
                if(window!=null && !window.IsDisposed) window.RefreshView(view,history,checkedAt,Dark());
            } finally { reading=false; }
        }
        protected override void ExitThreadCore() {
            stopped=true; timer.Dispose();
            tray.Visible=false;tray.ContextMenuStrip.Dispose();tray.Dispose();
            if(window!=null) window.Dispose();
            fresh.Dispose();waiting.Dispose();base.ExitThreadCore();
        }
    }
    static class Program {
        [STAThread] static void Main() {
            bool first;
            using(var mutex=new Mutex(true,@"Local\FS-FC27-QuoteTray",out first)) {
                if(!first) return;
                Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new Tray());
            }
        }
    }
}
