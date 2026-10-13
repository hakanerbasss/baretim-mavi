# Veri dosyaları nasıl güncellenir

Baretim Mavi bu depodaki dosyaları `raw.githubusercontent.com/hakanerbasss/baretim-mavi/main/` adresinden okur.
**`main` dalındaki her değişiklik canlıdır** — kullanıcılar bir sonraki yenilemede yeni rakamı görür.

| Dosya | Ne içerir | Nasıl güncellenir |
|---|---|---|
| `inflation_rates.json` | Yıllık TÜFE (geçmiş yıllar) ve yıl sonu tahminleri | **Kendiliğinden** — her gün TCMB tablosundan |
| `tax_parameters.json` | Kıdem tavanı (dönemli), asgari ücret, gelir vergisi dilimleri, SGK tavan katsayısı, bildirim metni | **Tek dokunuş** — rakam girilir, betik doğrular ve işler |
| `veri_durumu.json` | Son kontrol tarihi (ayda bir yazılır; depoyu "hareketli" tutar, zamanlanmış iş durmaz) | Kendiliğinden |

## Neden hepsi kendiliğinden değil?

TÜFE'nin makinece okunabilir, sabit adresli bir resmî kaynağı var (TCMB tablosu), o yüzden otomatik.
Kıdem tavanı, asgari ücret ve gelir vergisi dilimlerinin **yok** (genelge/Resmî Gazete metni; haber sitelerinden okumak
yanlış bir rakamı tüm kullanıcılara yayımlayabilir). Yanlış tazminat, geç gelen güncellemeden kötüdür.
Bu yüzden rakamı bir insan girer, betik yalnızca **doğrular ve işler**; vadesi gelince de issue açarak hatırlatır.

## Günlük iş (`.github/workflows/veri-guncelle.yml`)

1. Birim testlerini çalıştırır (bozuksa hiçbir şey yazmaz).
2. **TÜFE:** TCMB tablosunu okur. Yıllık ↔ aylık değerleri çapraz doğrular (sütun kayması, eksik ay, bozuk sayfa →
   hiçbir şey yazılmaz, iş kırmızı olur). Son iki tamamlanmış yılın değerini ve cari yıl sonu tahminini (son açıklanan
   12 aylık TÜFE) günceller. İleri yıl tahminleri (2027–2030) editoryaldır, dokunulmaz.
3. **Vade kontrolü:** Kıdem tavanı her 1 Ocak / 1 Temmuz'da değişir (duyuru ayın ilk günlerinde netleşir → 3 gün sonra
   hatırlatır). Yıl değişince asgari ücret + dilimler için hatırlatır. Hatırlatma = `veri-guncelle` etiketli issue;
   işlenince kendiliğinden kapanır.
4. Değişiklik varsa commit atar (`github-actions[bot]`).

## Yeni rakamı işlemek (örn. Ocak'ta)

**Actions → Veri güncelle → Run workflow** ve kutuları doldurun:

| Alan | Örnek | Not |
|---|---|---|
| `kidem_tavani` | `85000.50` | Önceki dönemden büyük, en çok %50 fazla olmalı. Binlik ayracı yok (`73.729,87` reddedilir). |
| `gecerlilik` | `2027-01-01` | Önceki dönemden sonra olmalı. Uygulama, işten çıkış tarihine göre doğru dönemi seçer. |
| `asgari_ucret` | `40000` | Brüt. Eskisinden küçük olamaz, %80'den fazla artamaz. |
| `dilimler` | `[[190000,0.15],[400000,0.20],[1500000,0.27],[5300000,0.35],[999999999,0.40]]` | Sınırlar ve oranlar artan; son sınır `999999999`. |
| `yil` | `2027` | Yalnızca tarife yılı değişiyorsa. |
| `duyuru` | `Kıdem tavanı 85.000,50 ₺ oldu.` | Boşsa rakamlardan otomatik yazılır. |

Yalnızca `duyuru` doldurulursa rakamlar değişmeden **sadece bildirim** gider (örn. yeni sürüm yayına çıkınca
"Net maaş hesabı düzeltildi, uygulamayı güncelleyin").

Yanlış girişte betik **hiçbir dosyayı değiştirmeden** hata verir. Doğru girişte `tax_parameters.json` güncellenir ve
`last_update` bugüne alınır.

## Kullanıcılara bildirim

Uygulama `tax_parameters.json` içindeki `last_update` değeri değişince yerel bildirim gösterir; metin `announcement`
alanındadır. Bu yüzden **rakam girişi = bildirim**. (TÜFE güncellemesi `last_update`'e dokunmaz: her ay bildirim yağmaz.)

- **Sürüm 2.76 ve sonrası:** uygulama kapalıyken de en geç ~12 saatte bir kontrol eder.
- **Sürüm 2.75 ve öncesi:** bildirim, kullanıcı hesap ekranlarını açtığında gösterilir; metin `announcement` değil, uygulamanın
  kendi genel metnidir ("Vergi dilimleri ve tazminat tavanı güncellendi. Hesaplarını yenile." veya asgari ücret değiştiyse onu söyleyen).
- Uygulamada Firebase (FCM) yok: Play Store'dan indirmiş birine "şimdi" anlık push göndermek mümkün değil.

## Elle çalıştırma (Termux / bilgisayar)

```bash
python3 tools/veri_guncelle.py tufe
python3 tools/veri_guncelle.py kontrol
python3 tools/veri_guncelle.py uygula --kidem-tavani 85000.50 --gecerlilik 2027-01-01
python3 -m unittest discover -s tools -p 'test_*.py'
```
