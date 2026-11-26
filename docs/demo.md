# Demo data: accounts and what to try

`docker compose up` fills an empty local database with demo data (`manage.py seed_demo`,
`apps/demo`). It is safe to run again: missing parts are added, nothing is duplicated.
Demo data is never loaded on Railway (production).

All passwords: **demo12345**

| Phone (login) | Role | Name | Branch |
|---|---|---|---|
| +998 90 000 00 01 | Direktor | Dilnoza Karimova | all |
| +998 90 000 00 11 | Filial administratori | Aziza Yusupova | Chilonzor |
| +998 90 000 00 12 | Sotuv menejeri | Sardor Rahimov | Chilonzor |
| +998 90 000 00 13 | O'qituvchi | Nodir Tursunov | Chilonzor |
| +998 90 000 00 14 | O'qituvchi | Malika Ergasheva | Chilonzor |
| +998 90 000 00 21 | Filial administratori | Bekzod Aliyev (may record Kirim) | Yunusobod |
| +998 90 000 00 22 | Sotuv menejeri | Kamola Saidova | Yunusobod |
| +998 90 000 00 23 | O'qituvchi | Jasur Xolmatov | Yunusobod |
| +998 90 000 00 24 | O'qituvchi | Shahnoza Qodirova | Yunusobod |

## What the demo contains

Two branches, courses and prices, groups with lessons and attendance, about 60 students
(some frozen, moved, left), leads in every stage with tasks and trial lessons, payments,
debts, discounts and installment plans, closed and open salary months (one owner-teacher at
65%), staff check-ins, store products with stock and sales, expenses (rent, utilities, a
center-wide Instagram budget), fixed salaries for administrators and managers, and:

- **Warnings** (Ogohlantirishlar): overdue debts, students who missed their last two lessons,
  and new leads nobody called.
- **Students who left with a reason** (report "O'quvchilar nega ketadi").
- **Bekzod Aliyev** was given "Kirim" in Sozlamalar → Foydalanuvchilar; Aziza Yusupova was not.

## A short tour

- **Direktor:** Bosh sahifa (schedule bar, tiles, chart) → Ogohlantirishlar → Hisobotlar →
  Filial foydasi → Xarajatlar → Maoshlar (fixed staff pay next to teachers) → Sozlamalar →
  Foydalanuvchilar → Bekzod (Qo'shimcha ruxsatlar).
- **Administrator (Aziza):** To'lov qabul qilish (success screen) → O'quvchilar on a phone
  (call / pay buttons) → Davomat → "Hammasi keldi" → Ombor (no Kirim button). Then log in
  as **Bekzod**: Ombor has "Kirim".
- **Sales manager (Sardor):** Lidlar board (drag a card, then "Ortga qaytarish") →
  Ogohlantirishlar (leads only, no money) → Vazifalar.
- **Teacher (Nodir):** Bosh sahifa (Keldim with "your first lesson starts at …", Maoshim
  tile) → Davomat → Maoshim.

Not in the demo: Telegram (needs a real bot token and phones) and GPS check-in from a real
phone (use "Xodimlar davomati → qo'lda" as the Direktor instead).
