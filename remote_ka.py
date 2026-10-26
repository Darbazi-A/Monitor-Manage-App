"""
The phone pages in Georgian: exact pieces of each page and their Georgian, applied
when the app runs in Georgian. The pieces carry their surroundings (a tag, quotes)
so that nothing the page's code relies on - a state name, an id - is touched.
"""
from __future__ import annotations

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
