#!/usr/bin/env python3
"""Baretim Mavi veri dosyalarını güncelleyen betik (uygulama bu dosyaları raw.githubusercontent.com'dan okur).

NE OTOMATİK, NE DEĞİL — bilerek ayrıldı:

* `tufe`   — OTOMATİK. inflation_rates.json'daki yıllık TÜFE'yi TCMB'nin sabit adresteki tablosundan günceller
             (TÜİK verisi; tablo 2005'ten beri tek sayfada). Tablo bozulursa (sütun kayması vb.) yıllık ↔ aylık
             çapraz doğrulaması tutmaz ve betik HİÇBİR ŞEY YAZMAZ.
* `kontrol`— OTOMATİK UYARI. Kıdem tazminatı tavanı (1 Ocak / 1 Temmuz), asgari ücret ve gelir vergisi dilimleri
             (yılda bir) için "güncelleme zamanı geldi mi?" diye bakar; geldiyse GitHub'da issue açılması için
             liste döner.
* `uygula` — TEK DOKUNUŞ. Rakamları verilen değerlerle, doğrulayarak işler (tax_parameters.json) ve last_update'i
             günceller; uygulama last_update değişince kullanıcılara bildirim gösterir. Yalnızca `--duyuru` verilirse rakam
             değişmeden sadece bildirim gönderilir (örn. yeni sürüm yayına çıkınca "güncelleyin" duyurusu).

Neden tavan/asgari ücret/dilim otomatik OKUNMUYOR: bunların makinece okunabilir, sabit adresli resmî bir kaynağı yok
(haber sitelerinden okumak yanlış bir rakamı TÜM kullanıcılara yayımlayabilir). Yanlış net/tazminat, güncelleme
gecikmesinden daha kötü; bu yüzden rakamı bir insan girer, betik yalnızca doğrular ve işler.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
TAX = KOK / 'tax_parameters.json'
ENF = KOK / 'inflation_rates.json'
DURUM = KOK / 'veri_durumu.json'

TCMB_TUFE_URL = ('https://tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/'
                 'Istatistikler/Enflasyon+Verileri/Tuketici+Fiyatlari')
_SATIR = re.compile(r'(0[1-9]|1[0-2])-(\d{4})\D{1,40}?(-?\d+[.,]\d+)\D{1,20}?(-?\d+[.,]\d+)')
SON_YIL_SAYISI = 2        # yalnızca son iki TAMAMLANMIŞ yılın değeri güncellenir (eski yıllar farklı baz yıllı)


class VeriHatasi(Exception):
    """Doğrulama başarısız: dosyalara dokunulmaz."""


# ── TÜFE ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def tcmb_oku(html):
    """TCMB tablosu → {'YYYY-MM': (yillik_yuzde, aylik_yuzde)}."""
    metin = re.sub(r'<[^>]+>', ' ', html)
    metin = re.sub(r'&nbsp;|&amp;', ' ', metin)
    tablo = {}
    for ay, yil, yillik, aylik in _SATIR.findall(metin):
        try:
            tablo[f'{yil}-{ay}'] = (float(yillik.replace(',', '.')), float(aylik.replace(',', '.')))
        except ValueError:
            continue
    return tablo


def tcmb_dogrula(tablo):
    """Yıllık ↔ aylık çapraz doğrulama: son 3 ayın yıllık değeri, son 12 aylık değişimin bileşiğine (±0,15 puan) eşit olmalı.
    Sütunlar yer değiştirirse ya da satırlar kayarsa bu tutmaz."""
    if len(tablo) < 150:
        raise VeriHatasi(f'TCMB tablosu eksik okundu ({len(tablo)} satır)')
    aylar = sorted(tablo)
    for ay in aylar[-3:]:
        y, m = int(ay[:4]), int(ay[5:])
        carpim = 1.0
        for i in range(12):
            yy, mm = y, m - i
            while mm < 1:
                mm += 12
                yy -= 1
            anahtar = f'{yy}-{mm:02d}'
            if anahtar not in tablo:
                raise VeriHatasi(f'TCMB tablosunda {anahtar} yok (ardışık değil)')
            carpim *= 1 + tablo[anahtar][1] / 100
        hesap = (carpim - 1) * 100
        if abs(hesap - tablo[ay][0]) > 0.15:
            raise VeriHatasi(f'{ay}: yıllık {tablo[ay][0]} ile aylıklardan hesaplanan {hesap:.2f} tutmuyor (sütun düzeni değişmiş olabilir)')


def enflasyon_guncelle(enf, tablo):
    """(yeni sözlük, değişiklik listesi). Aynı veri → değişiklik yok."""
    tcmb_dogrula(tablo)
    yeni = json.loads(json.dumps(enf))
    degisen = []
    son_ay = max(tablo)
    son_yil, son_ayno = int(son_ay[:4]), int(son_ay[5:])
    tamam = son_yil if son_ayno == 12 else son_yil - 1          # son TAMAMLANMIŞ yıl
    for yil in range(tamam - SON_YIL_SAYISI + 1, tamam + 1):
        kayit = tablo.get(f'{yil}-12')
        if kayit is None:
            continue
        deger = round(kayit[0], 1)
        if yeni['rates'].get(str(yil)) != deger:
            yeni['rates'][str(yil)] = deger
            degisen.append(f'{yil} yıllık TÜFE → %{deger}')
    if son_ayno != 12:
        tahmin = round(tablo[son_ay][0], 1)           # yıl sonu tahmini: son açıklanan 12 aylık enflasyon
        if yeni['estimates'].get(str(son_yil)) != tahmin:
            yeni['estimates'][str(son_yil)] = tahmin
            degisen.append(f'{son_yil} yıl sonu tahmini → %{tahmin} ({son_ay} yıllık TÜFE)')
        yeni['rates'].pop(str(son_yil), None)
    else:
        yeni['estimates'].pop(str(son_yil), None)
        sonraki = str(son_yil + 1)
        if sonraki not in yeni['estimates']:
            yeni['estimates'][sonraki] = round(tablo[son_ay][0], 1)
            degisen.append(f'{sonraki} tahmini eklendi')
    if yeni.get('last_update') != son_ay:
        yeni['last_update'] = son_ay
        degisen.append(f'last_update → {son_ay}')
    if not [d for d in degisen if not d.startswith('last_update')]:
        yeni['last_update'] = enf.get('last_update')      # yalnızca tarih değiştiyse dosyayı boşuna değiştirme
        return enf, []
    return yeni, degisen


# ── Vade takibi ──────────────────────────────────────────────────────────────────────────────────────────────────

def bekleyenler(tax, bugun):
    """Güncelleme zamanı gelmiş ama işlenmemiş kalemler: [{'kod','baslik','govde'}]."""
    sonuc = []
    donem = datetime.date(bugun.year, 1 if bugun.month < 7 else 7, 1)
    gecmis = tax.get('severance_ceiling_history') or []
    # Tavan 1 Ocak ve 1 Temmuz'da değişir; duyuru memur zammıyla (TÜFE açıklandıktan sonra, ayın 3'ü) netleşir.
    if bugun >= donem + datetime.timedelta(days=3) and not any(h['from'] >= donem.isoformat() for h in gecmis):
        sonuc.append({
            'kod': 'kidem_tavani',
            'baslik': f'Kıdem tazminatı tavanı güncellenmeli ({donem.isoformat()} dönemi)',
            'govde': (f'{donem.isoformat()} tarihinde yeni dönem başladı ama `severance_ceiling_history` içinde bu dönem yok.\n\n'
                      'Resmî rakam: Hazine ve Maliye Bakanlığı **Mali ve Sosyal Haklar Genelgesi**. Doğrulayıp '
                      '**Actions → Veri güncelle → Run workflow** ekranından `kidem_tavani` ve `gecerlilik` '
                      f'(`{donem.isoformat()}`) girin; betik doğrular, dosyayı günceller ve uygulama kullanıcılara bildirim gösterir.')})
    if tax.get('year') and bugun.year > int(tax['year']) and bugun >= datetime.date(bugun.year, 1, 5):
        sonuc.append({
            'kod': 'yillik',
            'baslik': f'{bugun.year} asgari ücret ve gelir vergisi dilimleri güncellenmeli',
            'govde': (f'`tax_parameters.json` hâlâ {tax["year"]} yılını gösteriyor.\n\n'
                      '**Actions → Veri güncelle → Run workflow** ekranından `yil`, `asgari_ucret` ve `dilimler` '
                      '(JSON: `[[190000,0.15],[400000,0.20],...,[999999999,0.40]]`) girin. Kıdem tavanı dönemi '
                      'ayrı bir issue ile takip edilir.')})
    return sonuc


# ── Uygulama (doğrulayarak işleme) ──────────────────────────────────────────────────────────────────────────────

def _tarih(metin):
    try:
        return datetime.date.fromisoformat(metin)
    except (TypeError, ValueError):
        raise VeriHatasi(f'Geçersiz tarih (YYYY-AA-GG olmalı): {metin!r}')


def _sayi(deger, ad):
    """'73729.87' ve '73729,87' kabul edilir; binlik ayracı ('73.729,87') belirsiz olduğu için reddedilir."""
    metin = str(deger).strip()
    if ',' in metin and '.' not in metin:
        metin = metin.replace(',', '.')
    try:
        sayi = float(metin)
    except ValueError:
        sayi = float('nan')
    if not sayi == sayi or sayi in (float('inf'), float('-inf')):
        raise VeriHatasi(f'{ad} sayı olmalı (örn. 73729.87, binlik ayracı olmadan): {deger!r}')
    return sayi


def uygula(tax, bugun, kidem_tavani=None, gecerlilik=None, asgari_ucret=None, dilimler=None, yil=None, duyuru=''):
    """tax sözlüğünün güncellenmiş kopyasını döner; geçersiz girişte VeriHatasi."""
    yeni = json.loads(json.dumps(tax))
    mesajlar = []
    if (kidem_tavani is None) != (gecerlilik is None):
        raise VeriHatasi('kidem_tavani ve gecerlilik birlikte verilmeli')
    if kidem_tavani is not None:
        tutar = _sayi(kidem_tavani, 'kidem_tavani')
        baslangic = _tarih(gecerlilik)
        gecmis = sorted(yeni.get('severance_ceiling_history') or [], key=lambda h: h['from'])
        if gecmis:
            son = gecmis[-1]
            if baslangic.isoformat() <= son['from']:
                raise VeriHatasi(f'gecerlilik ({baslangic}) son dönemden ({son["from"]}) sonra olmalı')
            if not son['amount'] < tutar <= son['amount'] * 1.5:
                raise VeriHatasi(f'kıdem tavanı {tutar:.2f}: önceki {son["amount"]:.2f}den büyük ve en çok %50 fazla olmalı')
        gecmis.append({'from': baslangic.isoformat(), 'amount': round(tutar, 2)})
        yeni['severance_ceiling_history'] = gecmis
        yeni['severance_ceiling'] = round(tutar, 2)
        mesajlar.append(f'Kıdem tazminatı tavanı {_tl(tutar)} ₺ oldu ({baslangic.day} {_AY[baslangic.month - 1]} {baslangic.year}).')
    if asgari_ucret is not None:
        tutar = _sayi(asgari_ucret, 'asgari_ucret')
        eski = float(yeni['min_wage_gross'])
        if not eski <= tutar <= eski * 1.8:
            raise VeriHatasi(f'asgari ücret {tutar:.2f}: önceki {eski:.2f}den küçük olamaz ve %80den fazla artamaz')
        yeni['min_wage_gross'] = tutar if tutar != int(tutar) else int(tutar)
        mesajlar.append(f'Asgari ücret {_tl(tutar)} ₺ brüt oldu.')
    if dilimler is not None:
        liste = _json(dilimler) if isinstance(dilimler, str) else dilimler
        yeni['tax_brackets'] = _dilimleri_dogrula(liste)
        mesajlar.append('Gelir vergisi dilimleri güncellendi.')
    if yil is not None:
        try:
            yil = int(yil)
        except (TypeError, ValueError):
            raise VeriHatasi(f'yil tam sayı olmalı: {yil!r}')
        if yil < int(yeni.get('year') or 0):
            raise VeriHatasi('yil geriye gidemez')
        yeni['year'] = yil
    if not mesajlar and yil is None and not (duyuru or '').strip():
        raise VeriHatasi('Güncellenecek bir şey verilmedi')
    yeni['sgk_ceiling_multiplier'] = yeni.get('sgk_ceiling_multiplier', 9)
    yeni['last_update'] = bugun.isoformat()
    yeni['announcement'] = (duyuru or ' '.join(mesajlar) + ' Hesaplarını yenile.').strip()
    return yeni


def _json(metin):
    try:
        return json.loads(metin)
    except ValueError:
        raise VeriHatasi(f'dilimler geçerli JSON olmalı, örn. [[190000,0.15],[999999999,0.40]]: {metin!r}')


def _dilimleri_dogrula(liste):
    if not isinstance(liste, list) or not 2 <= len(liste) <= 8:
        raise VeriHatasi('dilimler 2-8 çiftlik bir liste olmalı')
    sonuc, onceki_sinir, onceki_oran = [], 0, 0
    for cift in liste:
        try:
            sinir, oran = float(cift[0]), float(cift[1])
        except (TypeError, ValueError, IndexError):
            raise VeriHatasi(f'Geçersiz dilim: {cift!r}')
        if sinir <= onceki_sinir or not onceki_oran < oran < 1:
            raise VeriHatasi('dilim sınırları ve oranları artan olmalı (oran 0-1 arası)')
        onceki_sinir, onceki_oran = sinir, oran
        sonuc.append({'limit': int(sinir) if sinir == int(sinir) else sinir, 'rate': oran})
    if sonuc[-1]['limit'] < 999999999:
        raise VeriHatasi('son dilimin sınırı 999999999 olmalı ("ve üzeri")')
    return sonuc


_AY = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']


def _tl(x):
    return f'{x:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


# ── Dosya yazma (okunabilir biçim korunur) ───────────────────────────────────────────────────────────────────────

def tax_yaz(yol, tax):
    """tax_parameters.json'u mevcut biçime yakın yazar: dilimler ve tavan dönemleri tek satırda."""
    satir = []
    for k, v in tax.items():
        if k in ('tax_brackets', 'severance_ceiling_history'):
            ogeler = ',\n'.join('    ' + json.dumps(o, ensure_ascii=False) for o in v)
            satir.append(f'  {json.dumps(k)}: [\n{ogeler}\n  ]')
        else:
            satir.append(f'  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}')
    yol.write_text('{\n' + ',\n'.join(satir) + '\n}\n', encoding='utf-8')


def json_yaz(yol, veri):
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def durum_guncelle(yol, bugun, bekleyen, tufe_son_ay):
    """Haftalık değil AYLIK yazılır: depoda 60 gün hareket olmazsa GitHub zamanlanmış işleri durdurur; ayda bir commit bunu önler."""
    onceki = json.loads(yol.read_text(encoding='utf-8')) if yol.exists() else {}
    yeni = {'son_kontrol': bugun.isoformat(), 'tufe_son_ay': tufe_son_ay, 'bekleyen': [b['kod'] for b in bekleyen]}
    if (onceki.get('son_kontrol') or '')[:7] == bugun.isoformat()[:7] and onceki.get('tufe_son_ay') == tufe_son_ay \
            and onceki.get('bekleyen') == yeni['bekleyen']:
        return False
    json_yaz(yol, yeni)
    return True


def _tcmb_cek():
    import requests
    r = requests.get(TCMB_TUFE_URL, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (BaretimVeriBot)'})
    r.raise_for_status()
    return r.text


def main(argv=None, bugun=None, cek=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    alt = ap.add_subparsers(dest='komut', required=True)
    alt.add_parser('tufe')
    k = alt.add_parser('kontrol')
    k.add_argument('--json', action='store_true')
    u = alt.add_parser('uygula')
    for ad in ('kidem_tavani', 'gecerlilik', 'asgari_ucret', 'dilimler', 'yil', 'duyuru'):
        u.add_argument(f'--{ad.replace("_", "-")}', dest=ad, default=None)
    a = ap.parse_args(argv)
    bugun = bugun or datetime.date.today()
    try:
        if a.komut == 'tufe':
            tablo = tcmb_oku((cek or _tcmb_cek)())
            enf = json.loads(ENF.read_text(encoding='utf-8'))
            yeni, degisen = enflasyon_guncelle(enf, tablo)
            if degisen:
                json_yaz(ENF, yeni)
            print('\n'.join(degisen) or 'TÜFE: değişiklik yok')
            durum_guncelle(DURUM, bugun, bekleyenler(json.loads(TAX.read_text(encoding='utf-8')), bugun), max(tablo))
        elif a.komut == 'kontrol':
            liste = bekleyenler(json.loads(TAX.read_text(encoding='utf-8')), bugun)
            print(json.dumps(liste, ensure_ascii=False) if a.json else '\n'.join(b['baslik'] for b in liste) or 'Bekleyen yok')
        else:
            tax = json.loads(TAX.read_text(encoding='utf-8'))
            yeni = uygula(tax, bugun, a.kidem_tavani, a.gecerlilik, a.asgari_ucret, a.dilimler, a.yil, a.duyuru or '')
            tax_yaz(TAX, yeni)
            print(f'Güncellendi: {yeni["announcement"]}')
    except VeriHatasi as e:
        print(f'HATA: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
