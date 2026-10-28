"use strict";
// The dashboard's words: Georgian first, English underneath (the key). The cloud's own messages too.
const KA = {
  "never": "არასდროს", "just now": "ახლახან", "{0} min ago": "{0} წუთის წინ", "{0} h ago": "{0} საათის წინ",
  "Cancel": "გაუქმება", "Halls": "დარბაზები", "Journal": "ჟურნალი", "People": "ადამიანები", "Account": "ანგარიში",
  "Sign out": "გასვლა", "viewer": "მნახველი", "operator": "ოპერატორი", "admin": "ადმინისტრატორი",
  "First administrator": "პირველი ადმინისტრატორი", "Sign in": "შესვლა",
  "A new Stage Cloud: make its first administrator with the setup key.": "ახალი Stage Cloud: შექმენით პირველი ადმინისტრატორი დაყენების გასაღებით.",
  "Every hall's Stage Display Controller, in one place.": "ყველა დარბაზის Stage Display Controller ერთ ადგილას.",
  "Setup key": "დაყენების გასაღები", "Name": "სახელი", "Password": "პაროლი", "Make it": "შექმნა",
  "That did not work.": "ვერ მოხერხდა.", "black / nothing": "შავი / ცარიელი", "closed": "დახურულია",
  "update {0} ready": "განახლება {0} მზადაა", "downloading {0}": "იტვირთება {0}", "Running order": "სცენარი",
  "step {0}/{1}": "ნაბიჯი {0}/{1}", "Slides": "სლაიდები", "live": "ეთერში",
  "Every hall with Stage Display Controller, as it is now.": "ყველა დარბაზი, სადაც Stage Display Controller აყენია - ახლანდელი მდგომარეობით.",
  "Add a hall": "დარბაზის დამატება", "Loading…": "იტვირთება…",
  "No halls yet. Add one, then type its code in the hall's program: Settings → Cloud.": "დარბაზები ჯერ არ არის. დაამატეთ, მერე მისი კოდი ჩაწერეთ დარბაზის პროგრამაში: Settings → Cloud.",
  "No halls yet.": "დარბაზები ჯერ არ არის.", "not paired yet": "ჯერ არ დაკავშირებულა", "online": "ჩართულია",
  "offline · {0}": "გათიშულია · {0}", "remote desk off": "დისტანციური მართვა გამორთულია", "Remote desk": "დისტანციური მართვა",
  "Open": "გახსნა", "Pair “{0}”": "„{0}“-ის დაკავშირება",
  "On the hall's computer: Stage Display Controller → Settings → Cloud. Type this address and this code, then Pair. The code works once, for 30 minutes.":
    "დარბაზის კომპიუტერზე: Stage Display Controller → Settings → Cloud. ჩაწერეთ ეს მისამართი და ეს კოდი, მერე დააჭირეთ Pair-ს. კოდი ერთხელ მუშაობს, 30 წუთის განმავლობაში.",
  "Address": "მისამართი", "Done": "მზადაა", "The hall's name": "დარბაზის სახელი", "Add": "დამატება",
  "Screens": "ეკრანები", "Screen": "ეკრანი", "State": "მდგომარეობა", "On it": "რა გადის", "LED strip": "LED ზოლი",
  "open": "ღიაა", "No status yet.": "მონაცემები ჯერ არ მოსულა.", "Problems and events": "პრობლემები და მოვლენები",
  "Nothing so far.": "ჯერ არაფერი.", "Commands": "ბრძანებები", "A message for the operator…": "შეტყობინება ოპერატორისთვის…",
  "Show the message on the desk": "შეტყობინების ჩვენება მაგიდაზე", "Look for an update": "განახლების შემოწმება",
  "Install the update now": "განახლების ახლავე დაყენება",
  "Installing closes the program for about a minute: the stage screens go dark meanwhile.": "დაყენებისას პროგრამა დაახლოებით ერთი წუთით დაიხურება: ამ დროს სცენის ეკრანები ჩაბნელდება.",
  "Computer": "კომპიუტერი", "Windows": "Windows", "On for": "ჩართულია", "{0} h": "{0} სთ", "Program on for": "პროგრამა ჩართულია",
  "Free disk": "თავისუფალი დისკი", "Sound": "ხმა", "Phone remote": "ტელეფონის პულტი", "on · {0} phone(s)": "ჩართულია · {0} ტელეფონი",
  "off": "გამორთულია", "Laptops": "ლეპტოპები", "on · {0}": "ჩართულია · {0}", "Scene": "სცენა",
  "switched off in the hall": "დარბაზში გამორთულია", "allowed": "ნებადართულია", "Last status": "ბოლო მონაცემი",
  "Administration": "ადმინისტრირება", "Rename…": "სახელის შეცვლა…", "Pair again (new code)…": "ხელახლა დაკავშირება (ახალი კოდი)…",
  "Remove the hall…": "დარბაზის წაშლა…", "Done.": "შესრულდა.",
  "Install the update now? The program closes, installs and opens again - about a minute with the stage screens dark.":
    "დავაყენო განახლება ახლავე? პროგრამა დაიხურება, დაყენდება და თავიდან გაიხსნება - დაახლოებით ერთი წუთი, სცენის ეკრანები ჩაბნელებული.",
  "Install now": "ახლავე დაყენება", "Rename": "სახელის შეცვლა", "Save": "შენახვა",
  "A new code: the computer that pairs with it becomes this hall, and the one paired now loses its access.":
    "ახალი კოდი: ვინც მას გამოიყენებს, ის კომპიუტერი გახდება ეს დარბაზი, ახლანდელი კი წვდომას დაკარგავს.",
  "Make a code": "კოდის შექმნა",
  "Remove “{0}” from Stage Cloud? Its computer is disconnected for good (it can be paired again as a new hall).":
    "წავშალო „{0}“ Stage Cloud-იდან? მისი კომპიუტერი სამუდამოდ გაითიშება (შეიძლება თავიდან დაკავშირდეს, როგორც ახალი დარბაზი).",
  "Remove": "წაშლა", "Back": "უკან", "connected": "დაკავშირებულია", "reconnecting…": "ხელახლა უკავშირდება…",
  "Connecting to the hall…": "დარბაზთან დაკავშირება…", "The hall did not answer.": "დარბაზმა არ უპასუხა.",
  "The hall is not connected.": "დარბაზი არ არის დაკავშირებული.", "Who did what, and when.": "ვინ, რა და როდის გააკეთა.",
  "When": "როდის", "Who": "ვინ", "Hall": "დარბაზი", "What": "რა",
  "Viewers see the halls. Operators also send commands and use the remote desk. Administrators also add halls and people.":
    "მნახველები დარბაზებს ხედავენ. ოპერატორები ბრძანებებსაც აგზავნიან და დისტანციურად მართავენ. ადმინისტრატორები დარბაზებსა და ადამიანებსაც ამატებენ.",
  "Add a person": "ადამიანის დამატება", "you": "თქვენ", "New password…": "ახალი პაროლი…", "Saved.": "შენახულია.",
  "Removed.": "წაიშალა.", "Remove {0}?": "წავშალო {0}?", "New password for {0}": "ახალი პაროლი: {0}", "Role": "როლი",
  "Password (8 or more characters)": "პაროლი (8 ან მეტი სიმბოლო)", "Change my password": "ჩემი პაროლის შეცვლა",
  "Password now": "ახლანდელი პაროლი", "New password (8 or more characters)": "ახალი პაროლი (8 ან მეტი სიმბოლო)",
  "Changing it signs you out everywhere.": "შეცვლისას ყველგან გამოხვალთ ანგარიშიდან.",
  // the new look
  "{0} d ago": "{0} დღის წინ", "Today": "დღეს", "Yesterday": "გუშინ", "slide {0} of {1}": "სლაიდი {0} / {1}",
  "+{0} more": "+{0} კიდევ", "Waiting for the hall's computer: Settings → Cloud, address and code.": "ველოდებით დარბაზის კომპიუტერს: Settings → Cloud, მისამართი და კოდი.",
  "Control": "მართვა", "all halls": "ყველა დარბაზი", "need attention": "ყურადღება სჭირდება", "Find a hall…": "დარბაზის ძებნა…",
  "No halls yet": "დარბაზები ჯერ არ არის", "No hall matches.": "ასეთი დარბაზი ვერ მოიძებნა.",
  "Add a hall here, then type its code in the hall's program: Settings → Cloud.": "დაამატეთ დარბაზი აქ, მერე მისი კოდი ჩაწერეთ დარბაზის პროგრამაში: Settings → Cloud.",
  "An administrator adds the halls.": "დარბაზებს ადმინისტრატორი ამატებს.",
  "On the hall's computer open Stage Display Controller → Settings → Cloud.": "დარბაზის კომპიუტერზე გახსენით Stage Display Controller → Settings → Cloud.",
  "Type the address and the code below, then Pair.": "ჩაწერეთ ქვემოთ მოცემული მისამართი და კოდი, მერე დააჭირეთ Pair-ს.",
  "Copy": "კოპირება", "Copied.": "დაკოპირდა.", "Code": "კოდი", "The code works once, for 30 minutes.": "კოდი ერთხელ მუშაობს, 30 წუთის განმავლობაში.",
  "Give it a name everyone knows - you get a code for its computer.": "დაარქვით სახელი, რომელსაც ყველა იცნობს - მიიღებთ კოდს მისი კომპიუტერისთვის.",
  "e.g. Assembly hall": "მაგ. საკონფერენციო დარბაზი", "More": "მეტი", "Message": "შეტყობინება", "On the stage now": "სცენაზე ახლა",
  "offline": "გათიშულია", "pictures need the remote desk": "სურათებს დისტანციური მართვა სჭირდება", "…": "…",
  "Message for the operator": "შეტყობინება ოპერატორს", "It opens on the hall's desk and by its clock, with your name.": "გამოჩნდება დარბაზის მაგიდაზე და საათთან, თქვენი სახელით.",
  "Write a message…": "დაწერეთ შეტყობინება…", "Send": "გაგზავნა", "Install version {0}?": "დავაყენო ვერსია {0}?",
  "The program closes, installs and opens again - about a minute with the stage screens dark.": "პროგრამა დაიხურება, დაყენდება და თავიდან გაიხსნება - დაახლოებით ერთი წუთი, სცენის ეკრანები ჩაბნელებული.",
  "Pair again (new code)": "ხელახლა დაკავშირება (ახალი კოდი)", "Remove the hall": "დარბაზის წაშლა", "Pair again": "ხელახლა დაკავშირება",
  "connecting…": "უკავშირდება…", "All halls": "ყველა დარბაზი", "Sees every hall and what is on its screens.": "ხედავს ყველა დარბაზს და რა გადის მათ ეკრანებზე.",
  "Also sends messages and updates, and runs halls from the remote desk.": "ასევე აგზავნის შეტყობინებებს და განახლებებს, და დისტანციურად მართავს დარბაზებს.",
  "Also adds halls and people.": "ასევე ამატებს დარბაზებსა და ადამიანებს.", "New password": "ახალი პაროლი",
  "They can no longer sign in.": "ის ვეღარ შევა საიტზე.", "Give them the password yourself; they can change it under Account.": "პაროლი თავად გადაეცით; შეცვლა „ანგარიშში“ შეუძლია.",
  "Look": "იერსახე", "Language": "ენა", "Theme": "თემა", "Auto": "ავტო", "Light": "ღია", "Dark": "მუქი",
  "Welcome": "მოგესალმებით", "Install": "დაყენება", "Update": "განახლება",
  "The event starts in 10 minutes.": "ღონისძიება 10 წუთში იწყება.", "Please check the microphones.": "გთხოვთ, შეამოწმეთ მიკროფონები.",
  "Please open the stage screens.": "გთხოვთ, ჩართეთ სცენის ეკრანები.", "Please call me.": "გთხოვთ, დამირეკეთ.",
  "The next speaker is ready.": "შემდეგი გამომსვლელი მზადაა.",
  // the cloud's answers
  "wrong setup key": "დაყენების გასაღები არასწორია", "already set up": "უკვე შექმნილია", "name and role": "სახელი და როლი",
  "password: at least 8 characters": "პაროლი: მინიმუმ 8 სიმბოლო", "that name is taken": "ეს სახელი დაკავებულია",
  "no such user": "ასეთი მომხმარებელი არ არსებობს", "the last administrator stays one": "ბოლო ადმინისტრატორი ადმინისტრატორად რჩება",
  "the last administrator stays": "ბოლო ადმინისტრატორი ვერ წაიშლება", "wrong password": "პაროლი არასწორია",
  "too many tries - wait a quarter of an hour": "ძალიან ბევრი მცდელობა - დაელოდეთ 15 წუთი",
  "wrong name or password": "სახელი ან პაროლი არასწორია", "a name": "სახელი", "no such hall": "ასეთი დარბაზი არ არსებობს",
  "the hall is not connected": "დარბაზი არ არის დაკავშირებული", "the hall did not answer": "დარბაზმა არ უპასუხა",
  "viewing only": "მხოლოდ ნახვა", "administrators only": "მხოლოდ ადმინისტრატორებისთვის",
  "operators and administrators only": "მხოლოდ ოპერატორებისა და ადმინისტრატორებისთვის", "unknown command": "უცნობი ბრძანება",
  "an empty message": "შეტყობინება ცარიელია", "disconnected": "კავშირი გაწყდა", "no answer": "პასუხი არ მოვიდა",
  "Running this hall from the dashboard is switched off here (Settings → Cloud).": "ამ დარბაზის საიტიდან მართვა აქ გამორთულია (Settings → Cloud).",
};

let lang = "ka";
try { lang = localStorage.getItem("stageCloudLang") || "ka"; } catch (e) { /* private window */ }
document.documentElement.lang = lang;
function setLang(code) {
  lang = code === "en" ? "en" : "ka";
  document.documentElement.lang = lang;
  try { localStorage.setItem("stageCloudLang", lang); } catch (e) { /* */ }
}
const t = text => (lang === "ka" && KA[text]) || text;

// the journal's lines, as the cloud writes them (English), in Georgian
const JOURNAL_KA = [
  [/^signed in from (.+)$/, "შევიდა ($1)"],
  [/^hall computer paired from (.+)$/, "დარბაზის კომპიუტერი დაკავშირდა ($1)"],
  [/^pairing code made$/, "შეიქმნა დაკავშირების კოდი"],
  [/^hall added: (.+)$/, "დაემატა დარბაზი: $1"],
  [/^hall removed: (.+)$/, "წაიშალა დარბაზი: $1"],
  [/^renamed: (.+)$/, "სახელი შეიცვალა: $1"],
  [/^user added: (.+) \((\w+)\)(?: from (.+))?$/, (_, n, r) => `დაემატა ${n} (${t(r)})`],
  [/^user removed: (.+)$/, "წაიშალა მომხმარებელი: $1"],
  [/^role of (.+): (\w+)$/, (_, n, r) => `${n} - როლი: ${t(r)}`],
  [/^own password changed$/, "შეცვალა საკუთარი პაროლი"],
  [/^password of (.+) reset$/, "$1-ს შეეცვალა პაროლი"],
  [/^file sent: (.+)$/, "გაიგზავნა ფაილი: $1"],
  [/^remote: (.+)$/, "დისტანციურად: $1"],
  [/^message: (.+) → (.+)$/, (_, m, r) => `შეტყობინება: ${m} → ${r === "ok" ? "შესრულდა" : r}`],
  [/^check_update → (.+)$/, (_, r) => `განახლების შემოწმება → ${r === "ok" ? "შესრულდა" : r}`],
  [/^install_update → (.+)$/, (_, r) => `განახლების დაყენება → ${r === "ok" ? "შესრულდა" : r}`],
];
const jt = text => {
  if (lang !== "ka") return text;
  for (const [pattern, replacement] of JOURNAL_KA) if (pattern.test(text)) return text.replace(pattern, replacement);
  return text;
};
const tf = (text, ...args) => t(text).replace(/\{(\d)\}/g, (_, i) => args[i] ?? "");
