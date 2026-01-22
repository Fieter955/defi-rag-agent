import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore


acronym_data = [
    {"keyword": "BAKPK", "full": "Biro Akademik, Kemahasiswaan, Perencanaan dan Kerjasama"},
    {"keyword": "BEM", "full": "Badan Eksekutif Mahasiswa"},
    {"keyword": "BIPA", "full": "Bahasa Indonesia bagi Penutur Asing"},
    {"keyword": "BK", "full": "Bimbingan Konseling"},
    {"keyword": "BKA", "full": "Bimbingan Karier Alternatif"},
    {"keyword": "BP", "full": "Bimbingan dan Penyuluhan"},
    {"keyword": "BSNP", "full": "Badan Standar Nasional Pendidikan"},
    {"keyword": "BUK", "full": "Biro Umum dan Keuangan"},
    {"keyword": "CP", "full": "Capaian Pembelajaran"},
    {"keyword": "D1", "full": "Diploma I"},
    {"keyword": "D-I", "full": "Diploma I"},
    {"keyword": "D2", "full": "Diploma II"},
    {"keyword": "D-II", "full": "Diploma II"},
    {"keyword": "D3", "full": "Diploma III"},
    {"keyword": "D-III", "full": "Diploma III"},
    {"keyword": "Dirjen Dikti", "full": "Direktur Jenderal Pendidikan Tinggi"},
    {"keyword": "DO", "full": "Drop Out"},
    {"keyword": "DPK", "full": "Daftar Peserta Kuliah"},
    {"keyword": "DPNA", "full": "Daftar Peserta Nilai Akhir"},
    {"keyword": "FBS", "full": "Fakultas Bahasa dan Seni"},
    {"keyword": "FE", "full": "Fakultas Ekonomi"},
    {"keyword": "FHIS", "full": "Fakultas Hukum dan Ilmu Sosial"},
    {"keyword": "FIP", "full": "Fakultas Ilmu Pendidikan"},
    {"keyword": "FKg", "full": "Fakultas Keguruan"},
    {"keyword": "FKIP", "full": "Fakultas Keguruan dan Ilmu Pendidikan"},
    {"keyword": "FMIPA", "full": "Fakultas Matematika dan Ilmu Pengetahuan Alam"},
    {"keyword": "FOK", "full": "Fakultas Olahraga dan Kesehatan"},
    {"keyword": "FPBS", "full": "Fakultas Pendidikan Bahasa dan Seni"},
    {"keyword": "FPIK", "full": "Fakultas Pendidikan Ilmu Keolahragaan"},
    {"keyword": "FPIPS", "full": "Fakultas Pendidikan Ilmu Pengetahuan Sosial"},
    {"keyword": "FPMIPA", "full": "Fakultas Pendidikan Matematika dan Ilmu Pengetahuan Alam"},
    {"keyword": "FPTK", "full": "Fakultas Pendidikan Teknologi dan Kejuruan"},
    {"keyword": "FTK", "full": "Fakultas Teknik dan Kejuruan"},
    {"keyword": "HMJ", "full": "Himpunan Mahasiswa Jurusan"},
    {"keyword": "HMPS", "full": "Himpunan Mahasiswa Program Studi"},
    {"keyword": "IAD", "full": "Ilmu Alamiah Dasar"},
    {"keyword": "IKIP", "full": "Institut Keguruan dan Ilmu Pendidikan"},
    {"keyword": "IP", "full": "Indeks Prestasi"},
    {"keyword": "IPG", "full": "Institut Pendidikan Guru"},
    {"keyword": "IPK", "full": "IP Kumulatif"},
    {"keyword": "IPTEK", "full": "Ilmu Pengetahuan dan Teknologi"},
    {"keyword": "ISBD", "full": "Ilmu Sosial dan Budaya Dasar"},
    {"keyword": "JIK", "full": "Jurusan Ilmu Keolahragaan"},
    {"keyword": "Kabag", "full": "Kepala Bagian"},
    {"keyword": "Kajur", "full": "Ketua Jurusan"},
    {"keyword": "Ka. Lab", "full": "Kepala Laboratorium"},
    {"keyword": "KDN", "full": "Kutipan Daftar Nilai"},
    {"keyword": "KHS", "full": "Kartu Hasil Studi"},
    {"keyword": "KKN", "full": "Kuliah Kerja Nyata"},
    {"keyword": "KKNI", "full": "Kerangka Kualifikasi Nasional Indonesia"},
    {"keyword": "KKL", "full": "Kuliah Kerja Lapangan"},
    {"keyword": "Koord. Prodi", "full": "Koordinator Program Studi"},
    {"keyword": "Korti", "full": "Koordinator Tingkat"},
    {"keyword": "KPA", "full": "Kartu Perkembangan Akademik"},
    {"keyword": "KRS", "full": "Kartu Rencana Studi"},
    {"keyword": "KTM", "full": "Kartu Tanda Mahasiswa"},
    {"keyword": "LP3M", "full": "Lembaga Pengembangan Pendidikan dan Penjaminan Mutu"},
    {"keyword": "LPPM", "full": "Lembaga Penelitian dan Pengabdian kepada Masyarakat"},
    {"keyword": "MIPA", "full": "Matematika dan Ilmu Pengetahuan Alam"},
    {"keyword": "MM", "full": "Multimedia"},
    {"keyword": "MPM", "full": "Majelis Permusyawaratan Mahasiswa"},
    {"keyword": "OTK", "full": "Organisasi Tata Kerja"},
    {"keyword": "PA", "full": "Pembimbing Akademik"},
    {"keyword": "PAP", "full": "Penilaian Acuan Patokan"},
    {"keyword": "PEP", "full": "Penelitian dan Evaluasi Pendidikan"},
    {"keyword": "PG PAUD", "full": "Pendidikan Guru Pendidikan Anak Usia Dini"},
    {"keyword": "PGSD", "full": "Pendidikan Guru Sekolah Dasar"},
    {"keyword": "PGTK", "full": "Pendidikan Guru Taman Kanak-Kanak"},
    {"keyword": "PKK", "full": "Pendidikan Kesejahteraan Keluarga"},
    {"keyword": "PLS", "full": "Pedidikan Luar Sekolah"},
    {"keyword": "PPL", "full": "Praktik Pengalaman Lapangan"},
    {"keyword": "PPB", "full": "Psikologi Pendidikan dan Bimbingan"},
    {"keyword": "PT", "full": "Perguruan Tinggi"},
    {"keyword": "PTIK", "full": "Pendidikan Teknologi Informatika dan Komputer"},
    {"keyword": "PTPG", "full": "Perguruan Tinggi Pendidikan Guru"},
    {"keyword": "RPL", "full": "Rekayasa Perangkat Lunak"},
    {"keyword": "RPS", "full": "Rencana Pembelajaran Semester"},
    {"keyword": "S", "full": "Skor Akhir"},
    {"keyword": "S1", "full": "Program Sarjana (Strata 1)"},
    {"keyword": "S2", "full": "Program Pascasarjana (Strata 2)"},
    {"keyword": "S3", "full": "Program Doktor (Strata 3)"},
    {"keyword": "SC", "full": "Sistem Cerdas"},
    {"keyword": "Sekjur", "full": "Sekretaris Jurusan"},
    {"keyword": "SIAK", "full": "Sistem Informasi Akademik"},
    {"keyword": "SK", "full": "Surat Keputusan"},
    {"keyword": "sks", "full": "satuan kredit semester"},
    {"keyword": "SKS", "full": "Sistem Kredit Semester"},
    {"keyword": "SKL", "full": "Surat Keterangan Lulus"},
    {"keyword": "SNPT", "full": "Standar Nasional Pendidikan Tinggi"},
    {"keyword": "STKIP", "full": "Sekolah Tinggi Keguruan dan Ilmu Pendidikan"},
    {"keyword": "Sub. Bagian", "full": "Sub Bagian"},
    {"keyword": "T", "full": "Tugas"},
    {"keyword": "TA", "full": "Tugas Akhir"},
    {"keyword": "TIK", "full": "Teknologi Informasi dan Komunikasi"},
    {"keyword": "TKJ", "full": "Teknik Komputer dan Jaringan"},
    {"keyword": "TP", "full": "Teknologi Pendidikan"},
    {"keyword": "UAS", "full": "Ujian Akhir Semester"},
    {"keyword": "UKT", "full": "Uang Kuliah Tunggal"},
    {"keyword": "Undiksha", "full": "Universitas Pendidikan Ganesha"},
    {"keyword": "UPT", "full": "Unit Pelaksana Teknis"},
    {"keyword": "UTS", "full": "Ujian Tengah Semester"},
    {"keyword": "WD", "full": "Wakil Dekan"},
    {"keyword": "WR 1", "full": "Wakil Rektor Bidang Akademik"},
    {"keyword": "WR I", "full": "Wakil Rektor Bidang Akademik"},
    {"keyword": "WR 2", "full": "Wakil Rektor Bidang Umum dan Keuangan"},
    {"keyword": "WR II", "full": "Wakil Rektor Bidang Umum dan Keuangan"},
    {"keyword": "WR 3", "full": "Wakil Rektor Bidang Kemahasiswaan dan Alumni"},
    {"keyword": "WR III", "full": "Wakil Rektor Bidang Kemahasiswaan dan Alumni"},
    {"keyword": "WR 4", "full": "Wakil Rektor Bidang Perencanaan, Kerjasama, dan Kehumasan"},
    {"keyword": "WR IV", "full": "Wakil Rektor Bidang Perencanaan, Kerjasama, dan Kehumasan"},
    {"keyword": "BK", "full": "Bimbingan Konseling"},
    {"keyword": "ILKOM", "full": "Ilmu Komputer"},
    {"keyword": "PRODI", "full": "Program Studi"},
    {"keyword": "MATKUL", "full": "Mata Kuliah atau Struktur Kurikulum"},
    {"keyword": "MATKUL", "full": "Struktur Kurikulum"},
    {"keyword": "SMT", "full": "Semester"},
    {"keyword": "SMS", "full": "Semester"},
    {"keyword": "MK", "full": "Matakuliah"},
    {"keyword": "MK", "full": "Struktur Kurikulum"},
    {"keyword": "Matakuliah", "full": "Struktur Kurikulum"},
    {"keyword": "Mata kuliah", "full": "Struktur Kurikulum"},
    {"keyword": "UNDIKSHA", "full": "Universitas Pendidikan Ganesha"},
    {"keyword": "NIP", "full": "Nomor Induk Pegawai"},
    {"keyword": "NIDN", "full": "Nomor Induk Dosen Nasional"},
    {"keyword": "NUPTK", "full": "Nomor Unik Pendidik dan Tenaga Kependidikan"},
]

try:
    cred = credentials.Certificate('C:\\Users\\Ilmu Komputer\\OneDrive\\Desktop\\portofolio\\RAG\\defi-rag-agent\\serviceAccountKey.json')
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Inisialisasi Firebase berhasil...")
except Exception as e:
    print(f"Gagal inisialisasi Firebase. Pastikan file 'serviceAccountKey.json' sudah benar. Error: {e}")
    exit()

batch = db.batch()

collection_name = "acronym_expansion"
collection_ref = db.collection(collection_name)
print(f"Mempersiapkan data untuk di-upload ke koleksi '{collection_name}'...")
for item in acronym_data:
    doc_ref = collection_ref.document()
    batch.set(doc_ref, item)

try:
    batch.commit()
    print(f"\n--- SUKSES! ---")
    print(f"{len(acronym_data)} dokumen berhasil ditambahkan ke koleksi '{collection_name}'.")
except Exception as e:
    print(f"\n--- GAGAL ---")
    print(f"Terjadi kesalahan saat meng-upload data: {e}")