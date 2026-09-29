"""
The phone pages in Georgian: exact pieces of each page and their Georgian, applied
when the app runs in Georgian. The pieces carry their surroundings (a tag, quotes)
so that nothing the page's code relies on - a state name, an id - is touched.
"""
from __future__ import annotations

PAGE_KA = (
    ('<html lang="en">', '<html lang="ka">'),
    ("<title>Stage remote</title>", "<title>სცენის რიმოუთი</title>"),
    ('<h1 id="head">Stage remote</h1>', '<h1 id="head">სცენის რიმოუთი</h1>'),
    ('<div class="cap">On the screens</div>', '<div class="cap">ეკრანებზე</div>'),
    ('<button id="mvtoggle">hide</button>', '<button id="mvtoggle">დამალვა</button>'),
    ('mvHidden ? "show" : "hide"', 'mvHidden ? "ჩვენება" : "დამალვა"'),
    ('<div class="cap" id="nowcap">Ready</div>', '<div class="cap" id="nowcap">მზადაა</div>'),
    ('<button class="go" id="go">NEXT ▶</button>', '<button class="go" id="go">შემდეგი ▶</button>'),
    ('<div class="cap">Next</div>', '<div class="cap">შემდეგი</div>'),
    ('<button id="back">◀ Back</button>', '<button id="back">◀ უკან</button>'),
    ('<button id="restart">↺ Start over</button>', '<button id="restart">↺ თავიდან</button>'),
    (">Running order · tap a step, then GO<", ">სცენარი · აირჩიეთ ნაბიჯი, მერე „წადი“<"),
    ('<button class="blackout" id="blackout">BLACKOUT</button>', '<button class="blackout" id="blackout">ჩაბნელება</button>'),
    ('>Screens</div>', '>ეკრანები</div>'),
    ('>Sound</div>', '>ხმა</div>'),
    ('<button id="silence">Silence</button>', '<button id="silence">სიჩუმე</button>'),
    ('<div class="cap">Presets</div>', '<div class="cap">პრესეტები</div>'),
    ('data-v="show">SHOW</button>', 'data-v="show">სცენარი</button>'),
    ('data-v="stage">STAGE</button>', 'data-v="stage">სცენა</button>'),
    ('data-href="/slides">SLIDES</button>', 'data-href="/slides">სლაიდები</button>'),
    (">Enter the PIN shown on the dashboard<", ">შეიყვანეთ პანელზე ნაჩვენები PIN<"),
    ('askPin("Wrong PIN")', 'askPin("არასწორი PIN")'),
    ('askPin("Too many tries - wait a minute")', 'askPin("ძალიან ბევრი ცდა - დაიცადეთ ერთი წუთი")'),
    ('sc.state === "live" ? "ON AIR" : sc.state.toUpperCase()',
     'sc.state === "live" ? "ეთერში" : ({black: "შავი", closed: "დახურული", rehearsal: "რეპეტიცია"}[sc.state] || sc.state)'),
    ('show.name || "Stage remote"', 'show.name || "სცენის რიმოუთი"'),
    ('`Now · step ${show.index + 1} of ${show.steps.length}` : (show.steps.length ? "Ready" : "No steps yet")',
     '`ახლა · ნაბიჯი ${show.index + 1} / ${show.steps.length}` : (show.steps.length ? "მზადაა" : "ნაბიჯები ჯერ არ არის")'),
    ('(show.steps.length ? "Press NEXT to start" : "Build the running order on the dashboard")',
     '(show.steps.length ? "დასაწყებად დააჭირეთ „შემდეგი“-ს" : "სცენარი პანელზე ააწყვეთ")'),
    ('"running " + mmss(show.elapsed)', '"მიმდინარეობს " + mmss(show.elapsed)'),
    ('(now ? "— end of the show —" : "—")', '(now ? "— ღონისძიების დასასრული —" : "—")'),
    ('`goes on by itself in ${Math.ceil(show.auto)} s`', '`თავისით გაგრძელდება ${Math.ceil(show.auto)} წამში`'),
    ('<li class="empty">No steps in this running order.</li>', '<li class="empty">ამ სცენარში ნაბიჯები არ არის.</li>'),
    ('data-go="${i}">GO</button>', 'data-go="${i}">წადი</button>'),
    ('esc(sc.file || "empty") : "closed"', 'esc(sc.file || "ცარიელი") : "დახურულია"'),
    ('esc(c.label || "empty")', 'esc(c.label || "ცარიელი")'),
    ('p === s.preset ? "on screens" : "load"', 'p === s.preset ? "ეკრანებზეა" : "ჩატვირთვა"'),
    ('<div class="empty">No presets saved.</div>', '<div class="empty">პრესეტები არ არის შენახული.</div>'),
    ('confirm("Back to before step 1? Nothing on stage changes until NEXT.")',
     'confirm("პირველ ნაბიჯამდე დაბრუნება? „შემდეგი“-მდე სცენაზე არაფერი შეიცვლება.")'),
    ('confirm(`Put “${b.dataset.preset}” on the screens?`)', 'confirm(`„${b.dataset.preset}“ ეკრანებზე გავიტანო?`)'),
)

SLIDES_KA = (
    ('<html lang="en">', '<html lang="ka">'),
    ("<title>Slides remote</title>", "<title>სლაიდების რიმოუთი</title>"),
    ('<a href="/">◀ Show</a><h1 id="name">Slides</h1>', '<a href="/">◀ სცენარი</a><h1 id="name">სლაიდები</h1>'),
    ('<div class="slide" id="cur">no presentation open</div>', '<div class="slide" id="cur">პრეზენტაცია არ არის გახსნილი</div>'),
    ('<div class="cap">NEXT</div>', '<div class="cap">შემდეგი</div>'),
    ('<div class="cap">NOTES</div>', '<div class="cap">შენიშვნები</div>'),
    ('<button id="next">NEXT ▶</button>', '<button id="next">შემდეგი ▶</button>'),
    ('<button id="black">Black</button><button id="live">Show on screen</button>',
     '<button id="black">შავი</button><button id="live">ეკრანზე ჩვენება</button>'),
    (">ENTER THE PIN SHOWN ON THE DASHBOARD<", ">შეიყვანეთ პანელზე ნაჩვენები PIN<"),
    ('document.title = "Slide clicker"', 'document.title = "სლაიდების კლიკერი"'),
    ('askPin("Wrong PIN")', 'askPin("არასწორი PIN")'),
    ('askPin("Too many tries - wait a minute")', 'askPin("ძალიან ბევრი ცდა - დაიცადეთ ერთი წუთი")'),
    ('"<span>end</span>"', '"<span>დასასრული</span>"'),
    ('"<span>preparing…</span>"', '"<span>მზადდება…</span>"'),
    ('textContent = "THIS CLICKER LINK HAS EXPIRED"', 'textContent = "კლიკერის ბმულს ვადა გაუვიდა"'),
    ('textContent = "Ask the stage desk for the new QR code."', 'textContent = "სთხოვეთ სცენის ოპერატორს ახალი QR კოდი."'),
    ('s.loaded ? s.name : "Slides"', 's.loaded ? s.name : "სლაიდები"'),
    ('"on screen " + mmss(s.elapsed)', '"ეკრანზე " + mmss(s.elapsed)'),
    ('!s.loaded ? "NOTHING OPEN" : s.black ? "BLACK" : s.live ? "LIVE · " + s.target : "NOT ON SCREEN"',
     '!s.loaded ? "არაფერია გახსნილი" : s.black ? "შავი" : s.live ? "ეთერში · " + s.target : "ეკრანზე არ არის"'),
    ('s.black ? "Lift black" : "Black"', 's.black ? "შავის მოხსნა" : "შავი"'),
    ('s.live ? "End presentation" : "Show on screen"', 's.live ? "პრეზენტაციის დასრულება" : "ეკრანზე ჩვენება"'),
    ('$("cur").textContent = "no presentation open"', '$("cur").textContent = "პრეზენტაცია არ არის გახსნილი"'),
    ('confirm("End the presentation and put the background back?")',
     'confirm("დავასრულო პრეზენტაცია და ფონი დავაბრუნო?")'),
)

EXPIRED_KA = (
    ('<html lang="en">', '<html lang="ka">'),
    ("<title>Link expired</title>", "<title>ბმულს ვადა გაუვიდა</title>"),
    ("<b>THIS CLICKER LINK HAS EXPIRED</b><p>Ask the stage desk for the new QR code.</p>",
     "<b>კლიკერის ბმულს ვადა გაუვიდა</b><p>სთხოვეთ სცენის ოპერატორს ახალი QR კოდი.</p>"),
)


def localized(page: str, pairs) -> str:
    for english, georgian in pairs:
        page = page.replace(english, georgian)
    return page
