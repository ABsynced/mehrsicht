"""Creates the demo RSS feeds in fixtures/rss/ for offline mode.

All outlets and headlines are INVENTED examples ("Medium A" ...), so the
demo never puts words in the mouth of a real newspaper.
Run: python fixtures/make_fixtures.py
"""
from pathlib import Path
from xml.sax.saxutils import escape

import yaml

HERE = Path(__file__).resolve().parent

DE = {
    "a": [("Rentenpaket schützt Millionen vor Altersarmut", "Der Bundestag debattiert das Rentenpaket. Sozialverbände loben, dass das Rentenniveau stabil bleiben soll. SPD und Grüne sehen einen Schutz vor Altersarmut.", "09:40"),
          ("Heizungsgesetz: Neue Fristen schützen Mieter", "Die Regierung legt neue Fristen für das Heizungsgesetz vor. Grüne betonen den Klimaschutz und mehr Förderung für Wärmepumpen.", "08:10"),
          ("Mietpreisbremse wird bis 2029 verlängert", "Die Mietpreisbremse wird bis 2029 verlängert. Mieterbund und SPD begrüßen die Verlängerung.", "07:30")],
    "b": [("Rentenpaket: Stabiles Rentenniveau für Millionen", "Im Bundestag beginnt die Debatte über das Rentenpaket. Das Rentenniveau soll bei 48 Prozent bleiben, Gewerkschaften begrüßen den Plan.", "09:55"),
          ("Geflüchtete: Länder fordern faire Verteilung", "Mehrere Länder streiten über die Verteilung von Geflüchteten. Hilfsorganisationen warnen vor überfüllten Unterkünften.", "08:45"),
          ("Verlängerung der Mietpreisbremse beschlossen", "Die Mietpreisbremse gilt bis 2029. Die Linke fordert einen bundesweiten Mietendeckel statt der Verlängerung.", "07:50"),
          ("Haushalt: Streit um Schuldenbremse spitzt sich zu", "Im Haushaltsausschuss streiten Koalition und Opposition über die Schuldenbremse. Grüne fordern Ausnahmen für Investitionen.", "06:40")],
    "c": [("Heizungsgesetz: Mehr Förderung für Wärmepumpen", "Neue Fristen im Heizungsgesetz: Die Förderung für Wärmepumpen steigt, Mieter sollen geschützt werden.", "08:20"),
          ("Mietpreisbremse: Verlängerung bis 2029", "Die Koalition verlängert die Mietpreisbremse bis 2029. Mieter in Großstädten profitieren.", "07:35"),
          ("Industrie: Auftragslage schwach, Beschäftigte in Sorge", "Die Industrie meldet den dritten Monat in Folge weniger Aufträge. Gewerkschaften fordern ein Investitionsprogramm.", "06:15"),
          ("Lehrermangel: Länder setzen auf Quereinsteiger", "Gegen den Lehrermangel wollen die Länder Quereinsteiger schneller zulassen. Die GEW warnt vor sinkender Qualität.", "05:30")],
    "d": [("Bundestag debattiert neues Rentenpaket", "Das Rentenpaket der Bundesregierung soll das Rentenniveau bei 48 Prozent sichern. Union und SPD verteidigen den Plan, die Opposition kritisiert die Kosten.", "10:05"),
          ("Heizungsgesetz: Neue Fristen für Hausbesitzer", "Die Bundesregierung stellt neue Fristen für das Heizungsgesetz vor. Betroffen sind vor allem neu eingebaute Heizungen.", "08:30"),
          ("Länder streiten über Verteilung von Geflüchteten", "Bei der Ministerpräsidentenkonferenz streiten die Länder über die Verteilung von Geflüchteten und die Kosten der Unterbringung.", "08:50"),
          ("Industrie meldet schwächere Auftragslage", "Die Aufträge der Industrie gehen den dritten Monat in Folge zurück, meldet das Statistische Bundesamt.", "06:20"),
          ("Streit um die Schuldenbremse im Haushaltsausschuss", "Der Haushaltsausschuss berät über den Bundeshaushalt. Umstritten ist, ob die Schuldenbremse gelockert wird.", "06:45"),
          ("Bahn: Neue Fahrpläne ab Dezember", "Die Bahn stellt den neuen Fahrplan vor. Auf mehreren Strecken fahren mehr Züge.", "05:10")],
    "e": [("Was das Rentenpaket für Beitragszahler bedeutet", "Der Bundestag debattiert das Rentenpaket. Der Beitragssatz könnte bis 2030 steigen, das Rentenniveau bleibt stabil.", "10:00"),
          ("Verteilung von Geflüchteten: Länder uneins", "Die Länder sind bei der Verteilung von Geflüchteten uneins. Der Bund soll mehr Geld für die Unterbringung geben.", "08:55"),
          ("Auftragslage der Industrie schwächer als erwartet", "Die Industrie erhält den dritten Monat in Folge weniger Aufträge. Ökonomen rechnen mit einer schwachen Konjunktur.", "06:25"),
          ("Lehrermangel: Quereinsteiger sollen schneller in Schulen", "Die Kultusminister der Länder wollen den Lehrermangel mit Quereinsteigern bekämpfen. Bis 2030 fehlen 80.000 Lehrkräfte, heißt es.", "05:40")],
    "f": [("Bundeshaushalt: Was die Schuldenbremse erlaubt", "Der Streit um die Schuldenbremse prägt die Beratungen im Haushaltsausschuss. Ökonomen sind uneins.", "06:50"),
          ("Länder planen Quereinstieg gegen Lehrermangel", "Wie groß der Lehrermangel ist, ist umstritten. Die Länder planen einen schnelleren Quereinstieg.", "05:45")],
    "g": [("Teure Rente: Die Jungen zahlen die Zeche", "Das Rentenpaket im Bundestag belastet junge Beitragszahler. Kritiker warnen: Die Rente wird ab 2027 faktisch halbiert.", "09:30"),
          ("Heizungsgesetz: Hausbesitzer fürchten neues Verbot", "Neue Fristen im Heizungsgesetz verunsichern Hausbesitzer. In sozialen Medien heißt es: Alle Gasheizungen müssen 2027 raus.", "08:05"),
          ("Geflüchtete: Kommunen am Limit, Länder streiten", "Die Länder streiten über die Verteilung von Geflüchteten. Kommunen beklagen hohe Kosten, CDU und AfD fordern eine Begrenzung.", "09:05"),
          ("Studie: Bürokratie kostet Mittelstand Milliarden", "Eine neue Studie beziffert die Kosten der Bürokratie für den Mittelstand auf 60 Milliarden Euro im Jahr.", "07:10"),
          ("Schuldenbremse: Union warnt vor neuen Schulden", "Im Haushaltsausschuss lehnt die Union eine Lockerung der Schuldenbremse ab. Neue Schulden belasten künftige Generationen.", "06:55")],
    "h": [("Rentenpaket: Wirtschaft warnt vor Milliardenkosten", "Wirtschaftsverbände kritisieren das Rentenpaket im Bundestag. Der CDU-Wirtschaftsflügel und die AfD sprechen von einer Belastung für die Jungen.", "09:20"),
          ("Verteilung von Geflüchteten: Kosten explodieren", "Im Streit der Länder über die Verteilung von Geflüchteten geht es vor allem um Kosten. Bayern fordert eine Obergrenze.", "09:10"),
          ("Industrie: Auftragslage bricht weiter ein", "Die Industrie verliert den dritten Monat in Folge Aufträge. Wirtschaftsverbände nennen Energiepreise als Grund.", "06:30"),
          ("Bürokratie-Studie: Mittelstand ächzt unter Vorschriften", "Laut einer Studie kostet Bürokratie den Mittelstand 60 Milliarden Euro jährlich. FDP und Union fordern Entlastung.", "07:15")],
    "i": [("Studie: Bürokratie bremst den Mittelstand", "Die Bürokratie belastet den Mittelstand mit 60 Milliarden Euro pro Jahr, so eine Studie.", "07:20"),
          ("Kommentar: Die Regierung hat jedes Maß verloren", "Ein Meinungsbeitrag über den Kurs der Regierung.", "05:00")],
}

EU = {
    "fr_a": [("EU-Gipfel ringt um gemeinsame Industriepolitik", "Beim EU-Gipfel streiten die Staats- und Regierungschefs über eine gemeinsame Industriepolitik gegenüber China und den USA. Frankreich fordert mehr Schutz.", "10:10"),
             ("Klimaziel 2040: Parlament streitet über Ausnahmen", "Das Europäische Parlament streitet über das Klimaziel 2040 und Ausnahmen für die Industrie.", "07:40")],
    "de_m": [("Gipfel in Brüssel: Suche nach gemeinsamer Industriepolitik", "Der EU-Gipfel berät über eine gemeinsame Industriepolitik. Deutschland bremst bei neuen gemeinsamen Schulden.", "10:00"),
             ("Asylpakt: Umsetzung verzögert sich", "Mehrere Staaten melden Verzögerungen bei der Umsetzung des Asylpakts. Die Kommission mahnt.", "09:00"),
             ("Mercosur-Abkommen: Bauern protestieren in Brüssel", "Gegen das Mercosur-Abkommen protestieren Bauern aus mehreren Ländern in Brüssel.", "08:00")],
    "it_m": [("EU-Gipfel: Industriepolitik im Fokus", "Italien unterstützt beim EU-Gipfel eine gemeinsame Industriepolitik und fordert Mittel für Energie.", "09:50"),
             ("Digitaler Euro: Was wirklich geplant ist", "Die EZB erklärt den digitalen Euro. Gerüchte, das Bargeld werde abgeschafft, verbreiten sich im Netz.", "06:30")],
    "es_l": [("Gipfel: Industriepolitik soll Arbeitsplätze sichern", "Beim EU-Gipfel zur Industriepolitik fordern Sozialdemokraten Schutz für Beschäftigte.", "09:45"),
             ("Asylpakt: Hilfsorganisationen kritisieren Verzögerungen", "Die Verzögerungen beim Asylpakt treffen vor allem Ankunftsländer, warnen Hilfsorganisationen.", "08:50"),
             ("Mercosur: Exportbranchen hoffen auf neue Märkte", "Spaniens Exportwirtschaft begrüßt das Mercosur-Abkommen trotz der Proteste der Bauern.", "07:55")],
    "pl_r": [("EU-Gipfel: Polen warnt vor Industriepolitik aus Brüssel", "Polen lehnt beim EU-Gipfel eine zentral gesteuerte Industriepolitik ab und fordert mehr nationale Spielräume.", "09:40"),
             ("Mercosur-Abkommen bedroht unsere Bauern", "Polnische Bauern protestieren gegen das Mercosur-Abkommen und billige Importe.", "08:05")],
    "nl_r": [("Asylpakt: Niederlande wollen strengere Regeln", "Die Niederlande fordern bei der Umsetzung des Asylpakts strengere Regeln und schnellere Rückführungen.", "08:40"),
             ("Klimaziel 2040: Kosten für Landwirte zu hoch", "Beim Klimaziel 2040 fordern Abgeordnete Ausnahmen für die Landwirtschaft.", "07:35")],
    "fr_r": [("Mercosur: Frankreichs Bauern auf der Straße", "Französische Bauern blockieren Straßen aus Protest gegen das Mercosur-Abkommen.", "08:10"),
             ("Asylpakt scheitert an der Realität", "Die Umsetzung des Asylpakts verzögert sich, Grenzländer fühlen sich allein gelassen.", "08:45")],
    "at_r": [("Bargeld in Gefahr? Sorge vor dem digitalen Euro", "Im Netz heißt es: Die EU schafft 2027 das Bargeld ab. Viele Leser sorgen sich um den digitalen Euro.", "06:20")],
    "de_l": [("Klimaziel 2040: Umweltverbände fordern Härte", "Umweltverbände warnen, Ausnahmen beim Klimaziel 2040 würden den Klimaschutz schwächen.", "07:30"),
             ("Mercosur: Umweltschützer sehen Regenwald in Gefahr", "Umweltverbände kritisieren das Mercosur-Abkommen und warnen vor Abholzung.", "07:50")],
    "be_m": [("Digitaler Euro: Bargeld bleibt", "Der digitale Euro soll Bargeld ergänzen, nicht ersetzen, betont die Kommission.", "06:25")],
}


def write(edition: str, data: dict) -> None:
    sources = {s["id"]: s for s in yaml.safe_load((HERE / f"sources_demo_{edition}.yaml").read_text(encoding="utf-8"))["sources"]}
    out_dir = HERE / "rss" / edition
    out_dir.mkdir(parents=True, exist_ok=True)
    for sid, items in data.items():
        name = sources[sid]["name"]
        entries = []
        for idx, (title, summary, time) in enumerate(items):
            entries.append(
                f"<item><title>{escape(title)}</title><description>{escape(summary)}</description>"
                f"<link>https://example.org/{sid}/{idx}</link>"
                f"<pubDate>Sat, 24 Oct 2026 {time}:00 +0000</pubDate></item>"
            )
        xml = (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{escape(name)}</title>'
               f"<link>https://example.org/{sid}</link><description>Beispiel-Feed</description>{''.join(entries)}</channel></rss>")
        (out_dir / f"{sid}.xml").write_text(xml, encoding="utf-8")


if __name__ == "__main__":
    write("de", DE)
    write("eu", EU)
    print("Demo-Feeds geschrieben.")
