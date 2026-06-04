# INNOVICH Project-3

Desktop vision inspection application สำหรับตรวจสอบชิ้นงานด้วยกล้อง พัฒนาด้วย Python, PyQt5 และ OpenCV

โปรเจคนี้ถูกจัด scope ให้เหลือเฉพาะ core functions ที่ใช้งานจริงสำหรับงานส่งมอบชุดนี้ โดยเน้นการตั้งค่า ROI, ตรวจสอบชิ้นงาน, อ่านโค้ด, นับ/ติดตามวัตถุ และงาน Sticker Inspection ปัจจุบัน

## Scope ที่ส่งมอบ

ระบบรองรับ 5 main modes โดย `Sticker Inspection` อยู่เป็นตัวเลือกย่อยใต้ `Detection`

| Mode | ความสามารถหลัก | ผลลัพธ์ที่แสดง |
| --- | --- | --- |
| Detection | ตรวจว่ามี object หรือไม่มี object และบอกตำแหน่งโดยประมาณ | `OBJECT PRESENT`, `NO OBJECT` |
| Detection > Sticker Inspection | ตรวจ sticker จาก reference ว่ามี/ไม่มี เสียหาย เอียง หรือกลับหัว | `PASS`, `FAIL = ...` |
| Defect Inspection | ตรวจ QC จาก master template เช่น สีผิด หรือรูปร่างผิด | `PASS (OK)`, `DEFECT COLOR (NG)`, `DEFECT SHAPE (NG)` |
| Classification | แยกประเภทจากสี รูปร่าง และขนาด | `CLASSIFIED: n`, `FAIL = Wrong Classification` |
| Code Reading | อ่าน Barcode, QR และ DataMatrix ตาม decoder ที่มีในเครื่อง | `CODE READ: n`, `NO CODE` |
| Counting / Tracking | นับจำนวนและ track วัตถุที่ผ่านเส้น | `PASSED: n` |

ฟังก์ชัน Measurement และ Positioning / Robot Guidance ไม่อยู่ใน scope ของโปรเจคนี้ และไม่ได้รวมอยู่ใน package ส่งมอบ

## Requirements

- Python 3.10 ขึ้นไป
- กล้อง USB หรือกล้องที่ OpenCV เปิดใช้งานได้
- macOS, Windows หรือ Linux ที่ติดตั้ง dependency ได้ครบ

Dependency หลักอยู่ใน `requirements.txt`

- PyQt5
- opencv-contrib-python
- NumPy

## Quick Start

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## ตั้งค่า Admin

สร้างไฟล์ `.env` จากตัวอย่าง

```bash
cp .env.example .env
```

แก้รหัสผ่านใน `.env` ก่อนใช้งานจริง

```text
VISION_ADMIN_USERNAME=admin
VISION_ADMIN_PASSWORD=your-secure-password
```

หมายเหตุ: ถ้าไม่ได้ตั้ง `VISION_ADMIN_PASSWORD` ระบบจะไม่อนุญาตให้เข้า admin settings

## วิธีใช้งานหน้าเครื่อง

1. เปิดโปรแกรมด้วย `python main.py`
2. เลือก operation mode ที่ต้องการจากหน้าต่างเลือกโหมด ถ้าต้องใช้ Sticker Inspection ให้กด `Detection` แล้วเลือก `Sticker Inspection`
3. โปรแกรมจะเข้าสู่หน้า operator ตามโหมดที่เลือก
4. กด `START CAMERA`
5. ถ้าต้องตั้งค่า/แก้ไขพารามิเตอร์ ให้กด `ADMIN LOGIN`
6. เลือก `COUNTING METHOD`: `Stop & Capture` สำหรับงานหยุดถ่ายทีละชิ้น หรือ `Conveyor` สำหรับงานวิ่งผ่านสายพาน โดยค่า conveyor แยกตามโหมดที่เลือก
7. ปรับ ROI, camera และ parameter ของ mode นั้น ๆ
8. กด logout หรือกลับมาหน้า operator เพื่อใช้งานจริง

การลาก ROI บน live view ทำได้เฉพาะหลัง `ADMIN LOGIN` เท่านั้น เพื่อป้องกัน operator แก้ตำแหน่งตรวจโดยไม่ตั้งใจ

โหมดการทำงานเลือกได้เฉพาะหน้าต่างแรกตอนเปิดโปรแกรมเท่านั้น หน้า Admin ใช้สำหรับปรับวิธีนับชิ้นงาน, camera, ROI และ parameter ของโหมดที่เลือกไว้แล้ว

ค่า slider ในหน้า Admin สามารถลากหรือพิมพ์ตัวเลขเองได้ ถ้าค่าที่พิมพ์เกินช่วง ระบบจะปรับกลับไปที่ค่าสูงสุดหรือต่ำสุดของช่องนั้นให้อัตโนมัติ รวมถึงกัน `Min Area` ไม่ให้มากกว่า `Max Area` และกัน ROI ไม่ให้หลุดขอบภาพ

เมื่อเลือก `Conveyor` ระบบจะนับจากผลตรวจของโหมดนั้น ๆ เช่น object ที่ Detection เจอ, object ที่ Classification แยกได้ หรือ code ที่อ่านได้จริง ไม่ใช้ contour tracker กลางไปจับทุกอย่างในภาพ ส่วน `Defect Inspection` และ `Sticker Inspection` ล็อกไว้ที่ `Stop & Capture` ก่อนเพื่อกันการนับซ้ำจากภาพสั่นหรือแสงเปลี่ยน

## Workflow ของแต่ละโหมด

### Detection

- ใช้ตรวจว่ามี object อยู่ใน ROI หรือไม่
- ปรับ `Threshold`, `Min Area`, `Max Area` ให้เหมาะกับขนาดชิ้นงาน
- ระบบแสดงตำแหน่ง object โดยประมาณ เช่น `X:135 Y:120 A:10578`

### Defect Inspection

- วางชิ้นงานดีไว้ใน ROI
- กด `CHANGE TEMPLATE (MASTER PIECE)`
- ระบบจะใช้ภาพ master เป็น reference สำหรับตรวจสีและรูปร่าง
- ปรับ `Color Tolerance`, `Min Defect Area` และ `Fixture Tolerance` เพื่อชดเชยสี/ตำแหน่ง fixture ตามหน้างาน
- ถ้าชิ้นงานต่างจาก master จะแสดง defect status
- โหมดนี้ใช้ `Stop & Capture` เท่านั้นในตอนนี้

### Classification

- ใช้แยกประเภท object จากสี รูปร่าง และขนาด
- สามารถเลือกกลุ่มสีเป้าหมายใน settings ได้
- ปรับ `Min Area` และ `Hue Margin` เพื่อ calibrate สี/ขนาดงานจริง
- ผลลัพธ์ตัวอย่างเช่น `Green/Square/Medium`

### Code Reading

- ใช้สำหรับอ่าน Barcode, QR และ DataMatrix
- QR ใช้ OpenCV โดยตรง
- ถ้า QR เป็นลิงก์ ระบบจะเก็บใน log เป็น `QR LINK: ...`
- ตั้ง `Expected Code` ได้ ถ้าอ่านคนละค่าจะเป็น `FAIL = Code Mismatch`
- Barcode/DataMatrix จะทำงานตาม backend ที่มีในเครื่อง เช่น OpenCV barcode หรือ optional decoder

### Counting / Tracking

- ใช้นับวัตถุที่ผ่านเส้น tracking ภายใน ROI
- ปรับ `Line Position`, `Min Area`, `Threshold`, `Polarity` และ `Adaptive Threshold` ให้เหมาะกับวัตถุจริง
- ผลลัพธ์หลักคือจำนวนที่ผ่านเส้น เช่น `PASSED: 10`
- ถ้าใช้ `Stop & Capture` ระบบจะนับจำนวนที่พบในภาพนิ่งและแสดง `ITEMS: n` โดยไม่วาดเส้นนับบนภาพ capture

### Sticker Inspection

- เลือก `Detection` จากหน้าแรก แล้วเลือก `Sticker Inspection` ใน dropdown
- วางสินค้างานดีให้ sticker อยู่ใน ROI
- กด `CHANGE STICKER REFERENCE`
- ปรับ `Match Threshold`, `Min Area` และ `Max Angle Error` ให้เหมาะกับ sticker จริง
- เมื่อต้องตรวจงาน ให้กด `CAPTURE IMAGE`
- ระบบจะบันทึกภาพ raw/result และแสดงผล inspection

ผลลัพธ์ที่เป็นไปได้

- `PASS`
- `FAIL = Sticker Missing`
- `FAIL = Sticker Damaged`
- `FAIL = Sticker Skewed`
- `FAIL = Sticker Upside-Down`
- `NO STICKER REF` ถ้ายังไม่ได้ตั้ง reference

ปุ่ม `CAPTURE IMAGE` ใช้เมื่อตั้ง `COUNTING METHOD` เป็น `Stop & Capture`

## ไฟล์และข้อมูลที่ระบบบันทึก

| ข้อมูล | ตำแหน่ง |
| --- | --- |
| ค่า mode, วิธีนับชิ้นงาน, camera, ROI และ parameter | `config/settings.json` |
| Sticker reference | `config/sticker_reference.png` |
| Event log รวมรายวัน | `logs/log_YYYY-MM-DD.csv` |
| Event log แยกตามโหมด | `logs/by_mode/<mode>/log_YYYY-MM-DD.csv` |
| Error traceback ของ worker กล้อง | `logs/thread_errors_YYYY-MM-DD.log` |
| ภาพ inspection ที่ capture และ metadata | `captures/YYYY-MM-DD/` |

ไฟล์ใน `config/`, `logs/` และ `captures/` เป็นข้อมูลหน้างานของเครื่องนั้น ๆ จึงไม่ถูกใส่ใน package ส่งมอบโดยอัตโนมัติ

Log แยกตามโหมดจะมีคอลัมน์เฉพาะของโหมดนั้น ๆ เช่น `QR Links` สำหรับ Code Reading, `Items` / `NG Items` สำหรับ Classification, `Match Percent` / `Angle Error` สำหรับ Sticker Inspection และ `Capture File` สำหรับภาพที่บันทึกจาก Stop & Capture

## Troubleshooting

### เข้า Admin ไม่ได้

- ตรวจว่าไฟล์ `.env` มีอยู่จริง
- ตรวจว่าได้ตั้ง `VISION_ADMIN_PASSWORD`
- ปิดและเปิดโปรแกรมใหม่หลังแก้ `.env`

### กล้องเปิดไม่ได้

- บน macOS ให้ไปที่ `System Settings > Privacy & Security > Camera` แล้วอนุญาตแอปที่ใช้รันโปรแกรม เช่น Terminal, iTerm, VS Code, PyCharm หรือแอปที่ package แล้ว
- ตรวจว่ากล้องไม่ถูกโปรแกรมอื่นใช้อยู่
- ลองเปลี่ยน `camera_index` จากหน้า settings
- ถอดเสียบกล้องใหม่ แล้วกด `START CAMERA` อีกครั้ง

### Sticker Inspection ขึ้น `NO STICKER REF`

- เข้า `ADMIN LOGIN`
- วางงานดีใน ROI แล้วกด `CHANGE STICKER REFERENCE`

### ขึ้น `CAPTURE SAVE FAILED`

- ตรวจสิทธิ์การเขียนโฟลเดอร์ `captures`
- ตรวจพื้นที่ disk
- ลองปิดโปรแกรมแล้วเปิดใหม่

### โปรแกรมไม่ปิดทันทีแต่ขึ้น error ระหว่างกล้องทำงาน

ระบบจะเก็บ traceback ไว้ที่

```text
logs/thread_errors_YYYY-MM-DD.log
```

ส่งไฟล์นี้พร้อมเวลาที่เกิดปัญหาเพื่อใช้วิเคราะห์สาเหตุจริง

## โครงสร้างโปรเจค

```text
.
├── main.py
├── requirements.txt
├── .env.example
├── algorithms/
│   ├── object_detect.py
│   ├── defect_detect.py
│   ├── classification.py
│   ├── code_reading.py
│   ├── line_crossing.py
│   └── sticker_inspect.py
├── core/
│   ├── auth_manager.py
│   ├── camera_thread.py
│   ├── logger.py
│   └── settings_store.py
├── ui/
│   ├── camera_view.py
│   ├── dashboard.py
│   ├── login_dialog.py
│   └── settings_window.py
├── config/
├── captures/
├── logs/
└── scripts/
    └── build_delivery.py
```

## สร้าง package สำหรับส่งลูกค้า

ใช้คำสั่งนี้เพื่อสร้าง zip ส่งมอบ

```bash
python3 scripts/build_delivery.py
```

ไฟล์จะถูกสร้างที่

```text
delivery/INNOVICH_Project-3_client.zip
```

package นี้จะไม่รวมข้อมูล runtime เช่น `.env`, log, capture, cache และ config ของเครื่องปัจจุบัน

## Checklist ก่อนส่งมอบ

- ตั้งค่า `.env` เฉพาะเครื่อง demo หรือเครื่องลูกค้า
- เปิดกล้องและตรวจว่า live view ทำงาน
- เข้า `ADMIN LOGIN` แล้วตั้ง ROI
- ตั้ง master template สำหรับ `Defect Inspection` ถ้าใช้งานโหมดนี้
- ตั้ง sticker reference สำหรับ `Sticker Inspection`
- ทดสอบ capture และดูไฟล์ใน `captures/YYYY-MM-DD`
- สร้าง zip ด้วย `python3 scripts/build_delivery.py`
