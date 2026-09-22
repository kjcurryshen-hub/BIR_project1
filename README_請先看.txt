生醫文獻全文檢索－完整可執行版

這一包已經包含所有必要程式，不需要和任何舊版合併：

  app.py       網站與介面
  engine.py    XML 解析、統計、搜尋與 BM25
  porter.py    Porter stemming
  pmc.py       PMID 轉 PMCID，以及下載 PMC XML
  data/        六篇 PMC XML（包含 PMC13559554）
  啟動網站.bat  Windows 快速啟動

執行方式：

1. 對 ZIP 按右鍵，選「解壓縮全部」。
2. 進入解壓縮後的 biomedical_ir_complete 資料夾。
3. 在資料夾空白處按 Shift＋滑鼠右鍵，選「在終端機中開啟」。
4. 輸入：

       python app.py

   如果電腦無法使用 python 指令，改輸入：

       py app.py

   也可以直接雙擊「啟動網站.bat」。

5. 瀏覽器開啟：

       http://127.0.0.1:8765

6. 關閉網站時，回到終端機按 Ctrl＋C。

目前統計規則：

- Words、Sentences、Characters 只計算摘要。
- 搜尋詞顯示次數只計算摘要。
- 搜尋範圍包含摘要與正文，不包含標題。
- 標題只顯示，不參與搜尋，也不會因查詢而反白。
- 小數視為一個 word；例如 0.65 是一個，0.44–0.97 是兩個。
- 左側可用標題、PMCID 或固定編號即時搜尋已載入的文章。
- 點文章標題會進入該篇文章的單篇搜尋模式。
- 每篇文章都有刪除按鈕；為避免誤刪，XML 會移至 data/trash，可手動救回。
- 刪除後，剩餘文章會依原順序自動重新編為 001、002、003……，不會留下缺號。
- 網站左側的「已刪除檔案」可查看垃圾資料夾內的 XML 檔名。
- 文章詳細頁顯示摘要，下面提供 PMC 原文連結。
- testing、tested、tests 會經 Porter stemming 歸為 test。
- xref 引用標籤會補上文字邊界，避免 testing10 黏成一個詞。

注意：

- 執行時不要刪除 pmc.py。
- data 資料夾會保存網站匯入的 XML 與文章編號。
- PMID 查詢與 PMC 原文連結需要網路。
- 程式只使用 Python 內建套件，不需要 pip install。
