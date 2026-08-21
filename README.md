# MediaSort

Aplikacja w Pythonie do pełnoekranowego przeglądania i sortowania zdjęć oraz
filmów, z konfigurowalnymi skrótami klawiszowymi i wbudowanym dialogiem do
szybkiego kopiowania/przenoszenia plików do wybranych folderów.

## Instalacja

Wymagany Python 3.9+.

```bash
pip install -r requirements.txt
```

Aplikacja korzysta z **PySide6** (Qt) wraz z modułem `QtMultimedia` do
odtwarzania wideo. Na Linuksie odtwarzanie wideo wymaga zainstalowanego
backendu multimedialnego (zwykle FFmpeg jest już dołączony do PySide6 —
sprawdź, czy widzisz komunikat `Using Qt multimedia with FFmpeg` przy
starcie). Jeśli dźwięk/wideo nie działają, doinstaluj systemowe biblioteki
GStreamer/FFmpeg zgodnie z dokumentacją Qt dla Twojej dystrybucji.

## Uruchomienie

Otwarcie całego folderu (start od pierwszego pliku alfabetycznie):

```bash
python main.py /sciezka/do/folderu/ze/zdjeciami
```

Otwarcie **konkretnego pliku** — aplikacja załaduje folder, w którym się on
znajduje, i od razu przeskoczy do tego pliku (strzałki `←`/`→` nadal
przełączają na inne pliki w tym samym folderze):

```bash
python main.py /sciezka/do/folderu/zdjecie.jpg
```

Jeśli nic nie zostanie podane, użyty zostanie bieżący katalog:

```bash
python main.py
```

Własny plik ustawień:

```bash
python main.py /sciezka/do/folderu --settings /sciezka/do/moje_ustawienia.json
```

Domyślnie ustawienia trzymane są w `mediasort/settings.json` (plik tworzony
automatycznie przy pierwszym uruchomieniu, jeśli nie istnieje).

## Funkcje

### Nawigacja
- `→` — następny plik w folderze (przy oglądaniu zdjęć); podczas oglądania
  wideo zamiast tego przewija o 15 s (patrz sekcja Wideo) — kontekst wideo
  ma pierwszeństwo dla tego klawisza.
- `←` — analogicznie, poprzedni plik przy zdjęciach / przewijanie wstecz
  przy wideo.
- `PgDown` / `PgUp` — zawsze przechodzą do następnego/poprzedniego pliku w
  folderze, **niezależnie od tego, czy aktualnie wyświetlane jest zdjęcie
  czy wideo** — to gwarantuje, że zawsze da się przejść od wideo do
  zdjęcia i z powrotem, nawet gdy `→`/`←` są akurat zajęte przewijaniem.
  Nawigacja zawija się na końcach listy.

### Informacje o pliku (mały tekst na ekranie)
- Lewy górny róg: `{nazwa pliku} ({numer}/{liczba wszystkich plikow})`,
  widoczne zawsze, aktualizowane przy każdej zmianie pliku.
- Prawy górny róg, tylko dla wideo: `{biezacy czas mm:ss} / {calkowity czas mm:ss}`,
  aktualizowane na żywo w trakcie odtwarzania. Jeśli plik jest jednocześnie
  zaznaczony (patrz nizej), etykieta czasu przesuwa się w dol, aby nie
  nachodzic na znacznik `[x]`.

### Zaznaczanie wielu plików
- `/` — zaznacza lub odznacza bieżący plik. Zaznaczenie utrzymuje się do
  zamknięcia aplikacji albo do zmiany przegladanego zestawu plikow (np.
  przez dialog Otworz/Przegladaj, `O`) - zaznaczenie z poprzedniego
  zestawu nie jest przenoszone.
- Gdy bieżący plik jest zaznaczony, w prawym górnym rogu ekranu pojawia
  się znacznik `[x]`.
- Okno dialogowe kopiuj/przenieś ma dodatkowy panel po prawej stronie:
  - **Kontekst operacji**: "Zaznaczone" (domyślnie) lub "Biezacy plik" —
    decyduje, czy `Enter`/`Alt+C`/`Alt+M` dotyczą wszystkich zaznaczonych
    plików, czy tylko aktualnie wyświetlanego. Jesli kontekst "Zaznaczone"
    jest wybrany, ale nic nie jest faktycznie zaznaczone, operacja domyslnie
    dotyczy biezacego pliku (bez dodatkowego ostrzezenia).
  - **Odwroc zaznaczenie (i)** — zaznacza wszystkie niezaznaczone pliki w
    folderze i odznacza dotychczas zaznaczone.
  - **Zaznacz wszystkie (a)** — zaznacza wszystkie pliki w folderze.
  - **Podsumowanie zaznaczenia** — trzy sekcje, "Zaznaczone", "Pozostale"
    i "Folder" (podglad zawartosci folderu aktualnie wybranego z listy
    lokalizacji docelowych), z małymi podglądami plików: jeśli w danej
    grupie są 3 pliki lub mniej, widać podgląd każdego z nich; w
    przeciwnym razie widać podgląd pierwszego i ostatniego pliku z liczbą
    plików pomiędzy nimi. Wideo pokazuje generyczną ikonkę odtwarzania
    (bez dekodowania klatki).
- **Filtruj (`F`)** — przełącza tryb pokazywania wyłącznie zaznaczonych
  plików:
  - Jeśli bieżący plik nie jest zaznaczony w chwili włączania filtra,
    aplikacja od razu przechodzi do następnego zaznaczonego pliku.
  - Dopóki filtr jest włączony, `→`/`←` przeskakują wyłącznie między
    zaznaczonymi plikami (z zawijaniem na końcach).
  - Etykieta w lewym górnym rogu przyjmuje wtedy format
    `{nazwa pliku} (x/y -selected)`, gdzie `x` to numer kolejny bieżącego
    pliku wśród zaznaczonych, a `y` to łączna liczba zaznaczonych plików.
  - Ponowne `F` wyłącza filtr i przywraca normalną nawigację/etykietę.
  - Jeśli nic nie jest zaznaczone, `F` nic nie robi (nie ma do czego
    filtrować). Filtr wyłącza się automatycznie, jeśli w jego trakcie
    zaznaczenie opróżni się do zera (np. po odznaczeniu ostatniego pliku
    albo po przeniesieniu wszystkich zaznaczonych plików).

### Zdjęcia
- Pełnoekranowe wyświetlanie na czarnym tle.
- `Esc` — zamyka aplikację.
- `→` — następne zdjęcie/plik w folderze.
- `←` — poprzednie zdjęcie/plik w folderze.
- Orientacja zdjęcia jest odczytywana z tagu EXIF `Orientation` (tak samo
  jak w innych przegladarkach), wiec zdjecia zrobione aparatem obroconym
  na bok wyswietlaja sie w poprawnej, pionowej orientacji.

### Wideo
- Pełnoekranowe odtwarzanie.
- `→` — przewinięcie o 15 s do przodu (interwał konfigurowalny).
- `←` — przewinięcie o 15 s do tyłu.
- `Spacja` lub **lewy przycisk myszy** (kliknięcie poza paskiem postępu) —
  pauzuje lub wznawia odtwarzanie.
- `E` — przeskakuje do **następnego znacznika czasu** (tagu) w biezacym
  pliku, wzgledem aktualnej klatki; `Q` — do **poprzedniego**. Bierze pod
  uwage WSZYSTKIE tagi-znaczniki czasu w tym pliku, niezaleznie od ich
  nazwy (a przy przegladaniu wg konkretnego tagu - rowniez znaczniki
  innych tagow, nie tylko tego przegladanego). Nawigacja zawija sie na
  koncach listy znacznikow. Dziala tylko podczas ogladania wideo.
- Pasek postępu:
  - normalnie zajmuje 0,5% wysokości ekranu,
  - gdy kursor znajduje się w dolnej ćwiartce ekranu, pasek rośnie do 10%
    wysokości ekranu i staje się półprzezroczysty (50% opacity),
  - przytrzymanie `Ctrl` powoduje "przybliżenie" paska — w momencie
    wciśnięcia klawisza zakres zamraża się na 25% długości filmu,
    wyśrodkowane na aktualnej klatce (zakres nie przesuwa się dalej,
    dopóki `Ctrl` jest trzymany, nawet jeśli film gra dalej),
  - **kliknięcie (lub przeciąganie z wciśniętym lewym przyciskiem myszy)
    na pasku przewija wideo do odpowiadającej pozycji** — w trybie
    normalnym względem całej długości filmu, a w trybie przybliżonym
    (`Ctrl`) względem aktualnie wyświetlanego, zamrożonego zakresu.

### Dialog operacji na plikach (kopiuj / przenieś)

Ten dialog słuzy wylacznie do kopiowania i przenoszenia - przegladanie
plikow (dawniej trzecia akcja "Otworz") zostalo wydzielone do osobnego
dialogu Otworz/Przegladaj (`O`), opisanego w kolejnej sekcji.

- `C` — otwiera dialog z domyślną akcją **Kopiuj**.
- `M` — otwiera dialog z domyślną akcją **Przenieś**.
- **W trybie Względnym**: `Enter` **nawiguje** do zaznaczonej pozycji na
  liście (wchodzi w podfolder albo cofa się przez `...`) zamiast wykonywać
  akcję — dzięki temu można swobodnie schodzić w głąb i wracać. Żeby mimo
  to wykonać domyślną akcję (kopiuj/przenieś) w trybie Względnym,
  użyj `Ctrl+Enter`.
- **W trybach Historia/Ulubione** (gdzie nie ma nawigacji po podfolderach):
  `Enter` normalnie wykonuje domyślną akcję, tak jak wcześniej.
- `Ctrl+Enter` — zawsze wykonuje domyślną akcję (kopiuj/przenieś),
  niezależnie od trybu.
- `Alt+C` — wymusza **kopiowanie**, niezależnie od tego, z jaką domyślną
  akcją dialog otwarto.
- `Alt+M` — wymusza **przeniesienie**, analogicznie.
- Po **kopiowaniu** dialog się zamyka, a aplikacja zostaje na tym samym pliku.
- Po **przeniesieniu** dialog się zamyka i automatycznie ładowany jest
  kolejny plik z listy.
- Jeśli kontekst operacji to "Zaznaczone", ale nic nie jest zaznaczone,
  operacja domyślnie dotyczy bieżącego pliku (patrz sekcja "Zaznaczanie").
- Strzałki `↑`/`↓` — nawigacja po liście lokalizacji (pierwsza pozycja jest
  zaznaczona domyślnie).
- Nad listą znajduje się pole lokalizacji, ktore normalnie odzwierciedla
  zaznaczona pozycje na liscie. Klikniecie na nim lub `F2` zamienia je w
  edytowalne pole tekstowe z ta sama wartoscia - mozna dowolnie wpisac
  wlasna sciezke:
  - `Enter` zatwierdza zmiane i od razu wykonuje domyslna akcje dialogu
    (kopiowanie albo przeniesienie) z wpisana wartoscia, niezaleznie od
    zaznaczenia na liscie,
  - `Esc` anuluje edycje (etykieta wraca do poprzedniej wartosci).
  - Po kliknieciu Kopiuj/Przenies system probuje uzyc dokladnie tej
    wartosci jako lokalizacji docelowej - jesli folder nie istnieje,
    zaproponuje jego utworzenie; jesli sciezka jest niepoprawna (np.
    wskazuje na istniejacy plik zamiast folderu), wyswietli blad i nie
    zamknie okna.
- Tryby listy lokalizacji (`R`/`H`/`F` przełączają tryb):
  - **Względny (R)** — pokazuje podfoldery folderu, w którym znajduje się
    bieżący plik. Pozycja `...` przenosi o poziom wyżej (niewidoczna, gdy
    jesteśmy w katalogu głównym systemu plików). Zaznaczenie dowolnego
    podfolderu i `Enter` wchodzi do niego (i tak dalej, dowolnie głęboko).
  - **Historia (H)** — do 20 ostatnio używanych lokalizacji (najnowsza na
    górze). Jeśli historia jest pusta, domyślnie wybrany jest folder
    bieżącego pliku.
  - **Ulubione (F)** — lista folderów ręcznie dodanych przez użytkownika.
    Domyślnie zaznaczana jest ostatnio użyta lokalizacja (jeśli jest na
    liście ulubionych).
- `Ctrl+D` (lub przycisk "Ulubione +/-") — dodaje/usuwa aktualnie wybraną
  lokalizację z ulubionych (dostępne w trybach Względnym i Historia; w
  trybie Ulubione pozwala tylko usunąć pozycję).
- Aplikacja zapamiętuje ostatnio używany tryb listy i przy następnym
  otwarciu dialogu domyślnie go przywraca (pierwsze uruchomienie = tryb
  Względny).

### Dialog Otworz / Przegladaj

Osobny dialog (klawisz `O`) do wybierania **co przegladac** - zastepuje
dawna akcje "Otworz" w dialogu kopiuj/przenies. Ma trzy kolumny obok
siebie:

1. **Folder** — dziala tak samo jak lista lokalizacji w dialogu
   kopiuj/przenies (tryby Wzgledny/Historia/Ulubione, `R`/`H`/`F`,
   nawigacja w podfoldery przez `Enter` w trybie Wzglednym, reczna edycja
   sciezki przez `F2`/klikniecie) - z ta roznica, ze **nic nie jest domyslnie
   zaznaczone**: wybor folderu jest opcjonalny. Przycisk "Wyczysc folder"
   czysci wybor.
   - Ponizej wyboru folderu jest checkbox **"Uwzglednij podfoldery"** —
     gdy zaznaczony, system pokazuje takze pliki z podfolderow wybranego
     folderu (domyslnie 1 poziom w glab, zeby uniknac przeszukiwania
     ogromnych drzew folderow). Glebokosc mozna zmienic w
     `settings.json` przez `browse_subfolder_depth` (0 = tylko sam
     folder, 1 = folder + bezposrednie podfoldery [domyslnie], 2 = takze
     ich podfoldery, itd.).
2. **Tag** — lista wszystkich znanych tagow, alfabetycznie, do wyboru
   jednego (albo wcale). Przycisk "Wyczysc tag" czysci wybor.
3. **Typ plikow** — "Zdjecia i wideo" (domyslnie), "Tylko zdjecia" albo
   "Tylko wideo".

Trzeba wybrac **folder LUB tag** (mozna oba) - jesli oba pola sa puste,
przycisk "Otworz" pokaze blad. Zasady laczenia:

- **Sam folder** (bez tagu) — pokazuje wszystkie pliki z tego folderu
  (odpowiedniego typu).
- **Sam tag** (bez folderu) — pokazuje wszystkie pliki z tym tagiem w
  calej bazie danych, **niezaleznie od folderu**, w ktorym sie znajduja
  (odpowiedniego typu).
- **Folder + tag** — pokazuje tylko pliki, ktore sa jednoczesnie w tym
  folderze **i** maja ten tag (czesc wspolna obu warunkow).

Na biezaco widac licznik "Znaleziono: N plikow" odzwierciedlajacy
aktualny wybor. Po zatwierdzeniu (`Enter` lub przycisk "Otworz")
aplikacja przelacza sie na wynikowa liste plikow - dziala na niej zwykla
nawigacja `→`/`←`/`PgUp`/`PgDown`, zaznaczanie, filtrowanie itd., dokladnie
jak przy zwyklym przegladaniu folderu (nawet jesli wynik obejmuje pliki z
wielu roznych folderow, bo pochodzi z filtrowania po tagu). Zaznaczenie
plikow jest resetowane przy kazdym takim przelaczeniu.

### Tags Library (biblioteka tagów)

Tagi i wskaźniki do plików przechowywane są w lokalnej bazie danych
SQLite (`mediasort/tags.db`, tworzonej automatycznie). Tag to krótki
napis (do 16 znakow, dluzsze sa ucinane; spacje w srodku sa dozwolone).
Ten sam tag nie moze zostac przypisany dwa razy do tego samego pliku ani
dwa razy do tej samej sekundy wideo — proba taka jest po cichu ignorowana
(bez komunikatu bledu).

**Tagi a cykl zycia pliku:**
- Gdy plik z tagami zostanie **przeniesiony** (dialog kopiuj/przenies,
  akcja Przenies), wszystkie jego wpisy w bazie tagow **podazaja za nim**
  do nowej lokalizacji automatycznie - nie trzeba nic tagowac ponownie.
  Jesli plik docelowy przypadkiem mial juz ten sam tag, duplikat jest po
  cichu pomijany (bez bledu).
- Jesli podczas przegladania wg tagu (`Alt+T`) system natrafi na plik,
  ktory **juz nie istnieje** na dysku (np. zostal usuniety spoza
  aplikacji), automatycznie usuwa wszystkie jego wpisy z bazy tagow i
  **po cichu przechodzi do kolejnego pliku** - bez okna z bledem.

- **`Ctrl+T` — przypisz tag** — otwiera dialog z listą **ostatnio
  przypisywanych tagów** (najnowszy na górze); tagi już przypisane do
  bieżącego pliku są oznaczone `✓`. Można wybrać tag z listy albo wpisać
  nowy. Dialog zachowuje pełny zestaw funkcji dialogu operacji na
  plikach — kontekst "Zaznaczone/Biezacy plik", "Odwroc
  zaznaczenie"/"Zaznacz wszystkie" oraz podglądy "Zaznaczone"/"Pozostale".
  Trzeci panel podglądu, "Tag", pokazuje pierwszy i ostatni plik z
  aktualnie wpisanym/wybranym tagiem oraz łączną liczbę jego wystąpień.
  `Enter` (lub przycisk) przypisuje tag do zaznaczonych plików lub do
  bieżącego pliku (zależnie od kontekstu) — pliki już oznaczone tym tagiem
  są pomijane bez błędu.
- **`T` — zarządzanie tagami bieżącego pliku** — otwiera okno z polem
  tekstowym na tag, listą ostatnio używanych tagów po lewej (strzałki
  góra/dół wybierają, wypełniając pole tekstowe) oraz listą tagów
  bieżącego pliku po prawej (tagi na sekundach wideo pokazane jako
  `{TAG}@{MM:SS}`). Wideo jest automatycznie pauzowane przy otwarciu tego
  okna i wznawiane po zamknięciu.
  - `Enter` / przycisk "Tag plik" — przypisuje tag do całego pliku.
  - `Shift+Enter` / przycisk "Tag czas" (widoczny tylko dla wideo) —
    przypisuje tag do aktualnej sekundy odtwarzania.
  - Kazdy tag na liscie tagow biezacego pliku ma obok siebie link
    "Usun" — klikniecie usuwa dokladnie ten tag (jesli tag jest
    przypisany do kilku roznych sekund tego samego wideo, usuwa tylko
    wybrana instancje, nie ruszajac pozostalych).
- Podczas odtwarzania wideo wszystkie tagi przypisane do konkretnego
  czasu są widoczne w prawym górnym rogu, pod informacją o czasie. Kliknięcie
  tagu `{TAG}@{MM:SS}` przenosi odtwarzanie do przypisanej sekundy.
  - `Esc` / przycisk "Zamknij" — zamyka okno.
- **`Alt+T` — przeglądaj wg tagu** — otwiera dialog z listą **ostatnio
  przeglądanych tagów** (osobny od dialogu Otworz/Przegladaj - ten
  pokazuje kazde WYSTAPIENIE tagu z osobna, wlacznie ze znacznikami
  czasu w wideo):
  wybierasz tag (z listy albo wpisując), widzisz jego podgląd (pierwszy i
  ostatni plik + liczba wystąpień), i po zatwierdzeniu aplikacja pokazuje
  pierwszy plik z tym tagiem. Odtąd `→`/`←` przechodzą między kolejnymi
  **wystąpieniami** tagu — plik z tagiem na poziomie całego pliku, albo
  konkretna sekunda wideo (dziala to nawet podczas ogladania wideo, gdzie
  `→`/`←` normalnie przewijaja o 15s). Jeśli ten sam tag jest przypisany
  zarówno do całego wideo, jak i do sekundy 5:11 tego samego pliku,
  przeglądanie tego tagu najpierw pokaże plik od początku, a kolejne
  "Next" przeskoczy do 5:11 w tym samym pliku (bez przeladowania pliku -
  tylko przewiniecie). Etykieta pliku pokazuje wtedy format
  `{nazwa pliku} (x/y -tag:{nazwa tagu})`.
  - Nawigacja jest **świadoma aktualnej klatki**, nie tylko licznika: jesli
    uzytkownik rowniez przewinie/odtworzy wideo tak, ze aktualna pozycja
    znajdzie sie *pomiedzy* dwoma znacznikami czasu tego samego tagu (np.
    ogladajac plik z tagami na 1:01 i 3:00, a odtwarzacz jest na 2:00),
    `Next`/`Previous` poprawnie wybiora najblizszy kolejny/poprzedni
    znacznik wzgledem faktycznej pozycji, a nie sztywno wedlug kolejnosci
    na liscie.

## Konfiguracja skrótów klawiszowych

Każda akcja może mieć przypisany **jeden lub więcej** przycisk (klawisz i/lub
przycisk myszy) — wystarczy podać listę w `settings.json`. Stary format
(pojedynczy string zamiast listy) nadal działa, dla wygody i kompatybilności
wstecznej.

Klawisze zapisuje się w formacie Qt, np. `"Right"`, `"Escape"`, `"Space"`,
`"C"`, `"Alt+C"`, `"Ctrl+D"`. Przyciski myszy zapisuje się jako
`"MouseLeft"`, `"MouseRight"`, `"MouseMiddle"`, `"MouseBack"`,
`"MouseForward"` (opcjonalnie z modyfikatorem, np. `"Ctrl+MouseLeft"`).
Przypisanie przycisku myszy działa dla wszystkich konfigurowalnych akcji w
poniższych sekcjach. Pasek postępu wideo zachowuje obsługę lewym przyciskiem,
aby kliknięcie na nim zawsze przewijało materiał.

### Trzy sekcje, jedna zasada priorytetu

- **`navigation_keys`** — ogólne skróty aktywne zawsze podczas przeglądania
  (niezależnie od tego, czy wyświetlane jest zdjęcie czy wideo).
- **`video_keys`** — skróty aktywne **tylko** podczas oglądania wideo.
- **`file_dialog`** — skróty aktywne **tylko** gdy otwarte jest okno
  dialogowe kopiuj/przenieś **lub** dialog Otworz/Przegladaj (obydwa
  dzielą te same klawisze trybu listy: `R`/`H`/`F`, `F2`, `Esc`).

**Zasada priorytetu**: jeśli ten sam fizyczny przycisk jest ustawiony
zarówno w `navigation_keys`, jak i w sekcji kontekstowej (`video_keys`),
to działanie kontekstowe wygrywa **podczas gdy ten kontekst jest aktywny**.
W domyślnej konfiguracji `→`/`←` są przypisane zarówno do
`navigation_keys.next`/`prev`, jak i do `video_keys.seek_forward`/
`seek_backward` — więc podczas oglądania zdjęcia `→` przechodzi do
następnego pliku, a podczas oglądania wideo `→` przewija o 15s. Klawisze
`PgDown`/`PgUp` są ustawione **tylko** w `navigation_keys`, więc zawsze
działają jako "następny/poprzedni plik", **niezależnie od tego, czy aktualnie
oglądane jest zdjęcie czy wideo** — dzięki temu zawsze da się przejść od
wideo do zdjęcia i z powrotem, nawet gdy strzałki są akurat zajęte
przewijaniem.

```json
{
  "navigation_keys": {
    "quit": ["Escape"],
    "next": ["Right", "PgDown"],
    "prev": ["Left", "PgUp"],
    "show_copy_dialog": ["C"],
    "show_move_dialog": ["M"],
    "show_browse_dialog": ["O"],
    "toggle_select": ["/"],
    "toggle_filter": ["F"],
    "show_tag_selected_dialog": ["Ctrl+T"],
    "show_manage_tags_dialog": ["T"],
    "show_browse_tag_dialog": ["Alt+T"]
  },
  "video_keys": {
    "seek_forward": ["Right"],
    "seek_backward": ["Left"],
    "seek_seconds": 15,
    "toggle_pause": ["Space", "MouseLeft"],
    "next_timestamp_tag": ["E"],
    "prev_timestamp_tag": ["Q"]
  },
  "file_dialog": {
    "copy": ["Alt+C"],
    "move": ["Alt+M"],
    "confirm_action": ["Ctrl+Return"],
    "mode_relative": ["R"],
    "mode_history": ["H"],
    "mode_favourites": ["F"],
    "toggle_favourite": ["Ctrl+D"],
    "edit_location": ["F2"],
    "cancel": ["Escape"],
    "invert_selection": ["I"],
    "select_all": ["A"]
  }
}
```

Uwaga: tryb "przeglądaj wg tagu" (`Alt+T`) ma jeszcze wyzszy priorytet niz
kontekst wideo — dopoki jest aktywny, `→`/`←` zawsze przechodza miedzy
wystapieniami tagu, nawet podczas ogladania wideo (patrz sekcja Tags
Library powyzej).

Przykład: żeby zamykanie aplikacji działało zarówno pod `Esc`, jak i pod `Q`,
wystarczy ustawić `"quit": ["Escape", "Q"]`.

Można też zmienić listę rozszerzeń traktowanych jako zdjęcia/wideo
(`image_extensions`, `video_extensions`), limit historii
(`history_max_size`) oraz glebokosc przeszukiwania podfolderow w dialogu
Otworz/Przegladaj (`browse_subfolder_depth`, domyslnie 1).

## Struktura projektu

```
MediaSort/
├── main.py                     # punkt wejścia aplikacji
├── requirements.txt
├── README.md
└── mediasort/
    ├── config.py                # ustawienia, historia, ulubione
    ├── key_utils.py              # dopasowywanie skrótów klawiszowych
    ├── file_scanner.py            # skanowanie folderów z mediami
    ├── image_viewer.py            # widget wyświetlania zdjęć
    ├── video_viewer.py            # widget wideo + pasek postępu
    ├── thumbnails.py               # generowanie miniatur (podgladow)
    ├── selection_preview.py        # widget podsumowania zaznaczenia
    ├── file_operation_dialog.py   # dialog kopiuj/przenieś + zaznaczanie
    ├── tags_db.py                  # lokalna baza danych tagow (SQLite)
    ├── tag_assign_dialog.py        # dialog przypisywania tagu (Ctrl+T)
    ├── tag_management_dialog.py    # zarzadzanie tagami biezacego pliku (T)
    ├── tag_browse_dialog.py        # przegladanie plikow wg tagu (Alt+T)
    ├── main_window.py             # główne okno aplikacji
    ├── settings.json              # plik ustawień (auto-tworzony)
    └── tags.db                     # baza danych tagow (auto-tworzona)
```
