Notion link: https://app.notion.com/p/BIR_project1-3dcb0df373c08127b633f39bb1483a96?source=copy_link

BIR Project 1 — 規則與演算法簡介
1. Project 功能
讀取生醫文獻 XML / NXML，建立索引並提供關鍵字搜尋。
支援 AND、OR、PHRASE 三種搜尋模式。
使用 Porter stemming 處理詞形變化，並使用 BM25 對結果排序。
顯示摘要的 Words、Sentences、Characters，以及搜尋詞出現次數。
可選擇單篇文章搜尋，並匯出搜尋結果 CSV。
2. XML 與文字處理規則
article-title 只用來顯示；abstract 用於搜尋與摘要統計；body 用於全文搜尋與 BM25。
不納入參考文獻、補充資料等內容。xref 引用標籤會建立文字邊界，避免 testing10 這類錯誤斷詞。
Tokenization：**忽略一般標點符號；英文字、Unicode 字母與數字可成為 token；
小數如 0.05 保留為一個 word；HIV-1、TNF-α 等 ASCII 連字號詞保留為一個 token；/、%、<、en dash – 等符號主要作為分隔，不單獨計算為 word。
例如 α/β 會分成 α、β 兩個 token，而 Δ 本身可視為一個 token。; Δ G 視為一個 ; c.duapua12 視為兩個word(c和duapua12)。
4. 搜尋規則
模式
判定方式
AND
文章必須同時包含所有有效搜尋詞。
OR
文章只要包含任一有效搜尋詞即可。
PHRASE
詞幹需依輸入順序連續出現，且不跨段落。

5. 主要演算法
Stop words：AND / OR 會忽略 a、the、of 等常見詞；Words 統計仍會計算這些字。
Porter stemming：例如 testing、tested、tests 都轉成共同詞幹 test，提高詞形變化的匹配能力。
BM25：在符合條件的文章中，依詞頻、詞的稀有程度與文章長度進行排序；本系統使用 k1 = 1.2、b = 0.75。
6. 三項摘要統計
Words：摘要斷詞後的 token 數量，包含 stop words 與數字。
Sentences：以句號、問號、驚嘆號為主要句尾，並保護小數點與 e.g.、i.e.、Dr. 等常見縮寫。
Characters：摘要經空白正規化後的字串長度，包含空白與換行，不包含 XML 標籤。

