"""veri_guncelle.py birim testleri (ağ yok): python3 -m unittest discover -s tools -p 'test_*.py'"""
import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import veri_guncelle as v  # noqa: E402

BUGUN = datetime.date(2026, 10, 13)


def sahte_tablo(son_ay='2026-09', aylik=2.0, baslangic=2005):
    """Tutarlı bir TCMB tablosu: her ay %aylik; yıllık değer aylıkların bileşiği."""
    yil_son, ay_son = int(son_ay[:4]), int(son_ay[5:])
    aylar = []
    y, m = baslangic, 1
    while (y, m) <= (yil_son, ay_son):
        aylar.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    tablo = {}
    for i, (y, m) in enumerate(aylar):
        if i >= 11:
            carpim = 1.0
            for _ in range(12):
                carpim *= 1 + aylik / 100
            yillik = round((carpim - 1) * 100, 2)
        else:
            yillik = 0.0
        tablo[f'{y}-{m:02d}'] = (yillik, aylik)
    return tablo


def tablo_html(tablo, ters=False):
    """TCMB sayfasına benzer HTML: <tr><td>01-2026</td><td>yıllık</td><td>aylık</td></tr>."""
    satirlar = []
    for ay in sorted(tablo):
        y, a = tablo[ay]
        sutunlar = (a, y) if ters else (y, a)
        satirlar.append(f'<tr><td>{ay[5:]}-{ay[:4]}</td><td>{str(sutunlar[0]).replace(".", ",")}</td>'
                        f'<td>{str(sutunlar[1]).replace(".", ",")}</td></tr>')
    return '<html><body><table>' + '\n'.join(satirlar) + '</table></body></html>'


ENF = {'last_update': '2025-01', 'source': 'TUIK', 'rates': {'2024': 44.4, '2025': 30.0}, 'estimates': {'2026': 22.0, '2027': 18.0}}
TAX = {
    'year': 2026, 'last_update': '2026-02-02', 'min_wage_gross': 33030, 'severance_ceiling': 64948.77,
    'stamp_tax_rate': 0.00759, 'sgk_employee_rate': 0.14, 'unemployment_rate': 0.01,
    'tax_brackets': [{'limit': 190000, 'rate': 0.15}, {'limit': 999999999, 'rate': 0.40}],
    'severance_ceiling_history': [{'from': '2026-01-01', 'amount': 64948.77}],
}


class TufeTesti(unittest.TestCase):
    def test_html_okunur_ve_dogrulanir(self):
        tablo = sahte_tablo()
        okunan = v.tcmb_oku(tablo_html(tablo))
        self.assertEqual(set(okunan), set(tablo))
        v.tcmb_dogrula(okunan)
        self.assertAlmostEqual(okunan['2026-09'][0], tablo['2026-09'][0], places=2)

    def test_sutunlar_yer_degistirirse_reddedilir(self):
        okunan = v.tcmb_oku(tablo_html(sahte_tablo(), ters=True))
        with self.assertRaises(v.VeriHatasi):
            v.tcmb_dogrula(okunan)

    def test_eksik_tablo_reddedilir(self):
        with self.assertRaises(v.VeriHatasi):
            v.tcmb_dogrula(v.tcmb_oku('<table><tr><td>01-2026</td><td>10,5</td><td>1,0</td></tr></table>'))

    def test_ay_atlarsa_reddedilir(self):
        tablo = sahte_tablo()
        del tablo['2026-05']
        with self.assertRaises(v.VeriHatasi):
            v.tcmb_dogrula(tablo)

    def test_yil_ortasi_son_iki_tamamlanmis_yil_ve_tahmin(self):
        tablo = sahte_tablo('2026-09')
        tablo['2024-12'] = (44.38, tablo['2024-12'][1])
        tablo['2025-12'] = (30.89, tablo['2025-12'][1])
        yeni, degisen = v.enflasyon_guncelle(ENF, tablo)
        self.assertEqual(yeni['rates']['2025'], 30.9)
        self.assertEqual(yeni['rates']['2024'], 44.4)
        self.assertEqual(yeni['estimates']['2026'], round(tablo['2026-09'][0], 1))
        self.assertEqual(yeni['estimates']['2027'], 18.0)          # ileri yıl tahminlerine dokunulmaz
        self.assertEqual(yeni['last_update'], '2026-09')
        self.assertNotIn('2026', yeni['rates'])
        self.assertTrue(any('2025' in d for d in degisen))
        self.assertEqual(ENF['rates']['2025'], 30.0)               # girdi değişmez

    def test_ayni_veri_degisiklik_yok(self):
        tablo = sahte_tablo('2026-09')
        tablo['2025-12'] = (30.89, tablo['2025-12'][1])
        yeni, _ = v.enflasyon_guncelle(ENF, tablo)
        yeni2, degisen2 = v.enflasyon_guncelle(yeni, tablo)
        self.assertEqual(degisen2, [])
        self.assertEqual(yeni2, yeni)

    def test_aralik_ayi_yili_tamamlar(self):
        tablo = sahte_tablo('2026-12')
        yeni, _ = v.enflasyon_guncelle(ENF, tablo)
        self.assertEqual(yeni['rates']['2026'], round(tablo['2026-12'][0], 1))
        self.assertNotIn('2026', yeni['estimates'])
        self.assertIn('2027', yeni['estimates'])


class VadeTesti(unittest.TestCase):
    def test_temmuz_donemi_islenmemisse_bekler(self):
        kodlar = [b['kod'] for b in v.bekleyenler(TAX, BUGUN)]
        self.assertEqual(kodlar, ['kidem_tavani'])

    def test_islenmisse_bekleyen_yok(self):
        tax = json.loads(json.dumps(TAX))
        tax['severance_ceiling_history'].append({'from': '2026-07-01', 'amount': 73729.87})
        self.assertEqual(v.bekleyenler(tax, BUGUN), [])

    def test_donem_basindan_3_gun_beklenir(self):
        self.assertEqual(v.bekleyenler(TAX, datetime.date(2026, 7, 3)), [])
        self.assertEqual(len(v.bekleyenler(TAX, datetime.date(2026, 7, 4))), 1)

    def test_yeni_yil_asgari_ucret_ve_dilim(self):
        tax = json.loads(json.dumps(TAX))
        tax['severance_ceiling_history'].append({'from': '2026-07-01', 'amount': 73729.87})
        kodlar = [b['kod'] for b in v.bekleyenler(tax, datetime.date(2027, 1, 10))]
        self.assertIn('yillik', kodlar)
        self.assertIn('kidem_tavani', kodlar)
        self.assertEqual([b['kod'] for b in v.bekleyenler(tax, datetime.date(2027, 1, 2))], [])


class UygulaTesti(unittest.TestCase):
    def test_kidem_tavani_gecmise_eklenir(self):
        yeni = v.uygula(TAX, BUGUN, kidem_tavani='73729.87', gecerlilik='2026-07-01')
        self.assertEqual(yeni['severance_ceiling'], 73729.87)
        self.assertEqual(yeni['severance_ceiling_history'][-1], {'from': '2026-07-01', 'amount': 73729.87})
        self.assertEqual(yeni['last_update'], '2026-10-13')
        self.assertIn('73.729,87', yeni['announcement'])
        self.assertIn('1 Temmuz 2026', yeni['announcement'])
        self.assertEqual(yeni['sgk_ceiling_multiplier'], 9)
        self.assertEqual(TAX['severance_ceiling'], 64948.77)       # girdi değişmez

    def test_tavan_dusemez_ve_asiri_artamaz(self):
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='60000', gecerlilik='2026-07-01')
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='99000', gecerlilik='2026-07-01')       # >%50
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='73.729,87', gecerlilik='2026-07-01')   # binlik ayracı belirsiz
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='yetmiş', gecerlilik='2026-07-01')
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='nan', gecerlilik='2026-07-01')
        self.assertEqual(v.uygula(TAX, BUGUN, kidem_tavani='73729,87', gecerlilik='2026-07-01')['severance_ceiling'], 73729.87)

    def test_gecerlilik_geriye_gidemez_ve_ciftli_olmali(self):
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='70000', gecerlilik='2026-01-01')
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='70000')
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, kidem_tavani='70000', gecerlilik='01.07.2026')

    def test_asgari_ucret_sinirlari(self):
        yeni = v.uygula(TAX, BUGUN, asgari_ucret='38000')
        self.assertEqual(yeni['min_wage_gross'], 38000)
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, asgari_ucret='20000')
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, asgari_ucret='99999')

    def test_dilimler(self):
        dilimler = '[[190000,0.15],[400000,0.20],[1500000,0.27],[5300000,0.35],[999999999,0.40]]'
        yeni = v.uygula(TAX, BUGUN, dilimler=dilimler)
        self.assertEqual([d['limit'] for d in yeni['tax_brackets']], [190000, 400000, 1500000, 5300000, 999999999])
        self.assertEqual(yeni['tax_brackets'][1]['rate'], 0.2)
        for kotu in ('[[190000,0.15]]', '[[400000,0.15],[190000,0.20],[999999999,0.30]]',
                     '[[190000,0.20],[400000,0.15],[999999999,0.30]]', '[[190000,0.15],[400000,0.20]]',
                     '[[190000,0.15],[999999999,1.2]]', 'bozuk', '[[1,2,3],"x"]'):
            with self.assertRaises(v.VeriHatasi, msg=kotu):
                v.uygula(TAX, BUGUN, dilimler=kotu)

    def test_yil_geriye_gidemez(self):
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, yil='iki bin', asgari_ucret='40000')
        self.assertEqual(v.uygula(TAX, BUGUN, yil='2027', asgari_ucret='40000')['year'], 2027)
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN, yil='2025', asgari_ucret='40000')

    def test_bos_cagri_reddedilir(self):
        with self.assertRaises(v.VeriHatasi):
            v.uygula(TAX, BUGUN)

    def test_ozel_duyuru(self):
        yeni = v.uygula(TAX, BUGUN, asgari_ucret='38000', duyuru='Net maaş hesabı güncellendi.')
        self.assertEqual(yeni['announcement'], 'Net maaş hesabı güncellendi.')


class YazmaTesti(unittest.TestCase):
    def test_tax_yaz_okunabilir_ve_gecerli(self):
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / 'tax.json'
            yeni = v.uygula(TAX, BUGUN, kidem_tavani='73729.87', gecerlilik='2026-07-01')
            v.tax_yaz(yol, yeni)
            metin = yol.read_text(encoding='utf-8')
            self.assertEqual(json.loads(metin), yeni)
            self.assertIn('{"limit": 190000, "rate": 0.15}', metin)
            self.assertIn('₺', metin)                               # ensure_ascii kapalı
            self.assertTrue(metin.endswith('}\n'))

    def test_durum_ayda_bir_yazilir(self):
        with tempfile.TemporaryDirectory() as d:
            yol = Path(d) / 'durum.json'
            self.assertTrue(v.durum_guncelle(yol, datetime.date(2026, 10, 1), [], '2026-09'))
            self.assertFalse(v.durum_guncelle(yol, datetime.date(2026, 10, 20), [], '2026-09'))     # aynı ay, aynı durum
            self.assertTrue(v.durum_guncelle(yol, datetime.date(2026, 10, 21), [{'kod': 'kidem_tavani'}], '2026-09'))
            self.assertTrue(v.durum_guncelle(yol, datetime.date(2026, 11, 2), [{'kod': 'kidem_tavani'}], '2026-09'))


class UcuncuTarafKomutTesti(unittest.TestCase):
    """main(): dosya yolları geçici dizine çevrilip uçtan uca çalıştırılır."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.eski = (v.TAX, v.ENF, v.DURUM)
        v.TAX, v.ENF, v.DURUM = d / 'tax.json', d / 'enf.json', d / 'durum.json'
        v.TAX.write_text(json.dumps(TAX), encoding='utf-8')
        v.ENF.write_text(json.dumps(ENF), encoding='utf-8')

    def tearDown(self):
        v.TAX, v.ENF, v.DURUM = self.eski
        self.tmp.cleanup()

    def test_tufe_ucten_uca(self):
        tablo = sahte_tablo('2026-09')
        tablo['2025-12'] = (30.89, tablo['2025-12'][1])
        self.assertEqual(v.main(['tufe'], BUGUN, lambda: tablo_html(tablo)), 0)
        enf = json.loads(v.ENF.read_text(encoding='utf-8'))
        self.assertEqual(enf['rates']['2025'], 30.9)
        self.assertEqual(enf['last_update'], '2026-09')
        durum = json.loads(v.DURUM.read_text(encoding='utf-8'))
        self.assertEqual(durum['bekleyen'], ['kidem_tavani'])

    def test_bozuk_tabloda_dosya_degismez(self):
        onceki = v.ENF.read_text(encoding='utf-8')
        self.assertEqual(v.main(['tufe'], BUGUN, lambda: tablo_html(sahte_tablo(), ters=True)), 2)
        self.assertEqual(v.ENF.read_text(encoding='utf-8'), onceki)
        self.assertFalse(v.DURUM.exists())

    def test_uygula_komutu(self):
        self.assertEqual(v.main(['uygula', '--kidem-tavani', '73729.87', '--gecerlilik', '2026-07-01'], BUGUN), 0)
        self.assertEqual(json.loads(v.TAX.read_text(encoding='utf-8'))['severance_ceiling'], 73729.87)
        onceki = v.TAX.read_text(encoding='utf-8')
        self.assertEqual(v.main(['uygula', '--kidem-tavani', '10', '--gecerlilik', '2026-07-01'], BUGUN), 2)
        self.assertEqual(v.TAX.read_text(encoding='utf-8'), onceki)


if __name__ == '__main__':
    unittest.main()
