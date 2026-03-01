# BM25 Ranking with CockroachDB

BM25 (Best Matching 25) is a widely used, effective keyword-based ranking algorithm in information retrieval that ranks documents based on their relevance to a search query. It is used by search engines.

This current implmenetation, at the time of this writing, implements Okapi BM25 flavor. There are other variations that will be implemeted at some later point here. However, Okapi BM25 the default for many systems.


$$
\text{IDF}(q_i) = \ln \left( \frac{N - n(q_i) + 0.5}{n(q_i) + 0.5} + 1 \right)
$$


$$
\text{score}(D, Q) = \sum_{i=1}^{n} \text{IDF}(q_i) \cdot \frac{f(q_i, D) \cdot (k_1 + 1)}{f(q_i, D) + k_1 \cdot \left( 1 - b + b \cdot \frac{|D|}{\text{avgdl}} \right)}
$$


### Variable Definitions


| Symbol | Definition |
| :--- | :--- |
| $f(q_i, D)$ | **Term frequency**: How many times term $q_i$ appears in document $D$. |
| $|D|$ | **Document length**: Total number of words in document $D$. |
| $\text{avgdl}$ | **Average document length**: The mean length of all documents in the collection. |
| $k_1$ | **Scaling parameter**: Controls term frequency saturation (usually $1.2$ to $2.0$). |
| $b$ | **Normalization parameter**: Controls document length penalty (usually $0.75$). |
| $N$ | **Collection size**: Total number of documents in the system. |
| $n(q_i)$ | **Document frequency**: Number of documents containing term $q_i$. |
| $\text{IDF}(q_i)$ | **Inverse Document Frequency**: Weights rare terms more heavily than common ones. |


## Architecture

Given a table and a column containing the documents, two additional columns are added to instrument. The first stores the TSVECTOR of the source document. The Second stores the length of the document - the number of lexems in the document. These two instrumentation columns are updated via a trigger that is run when the row is inserted, updated or deleted.

In addition, there are two instrumentation tables.

`_tsv_terms`

`_tsv_corpus`