import json
import os
import re
from urllib import request
documents = [
    {
        "id": "doc-1",
        "title": "FastAPI 基础",
        "text": "FastAPI 是一个用于构建 API 的 Python Web 框架。它基于类型提示，可以自动生成 Swagger 文档。",
    },
    {
        "id": "doc-2",
        "title": "RAG 基础",
        "text": "RAG 的核心流程是先检索外部知识，再把相关内容交给模型生成答案。向量相似度可以帮助系统找到语义接近的文本片段。",
    },
    {
        "id": "doc-3",
        "title": "项目实现",
        "text": "本项目使用 RecursiveCharacterTextSplitter 切分知识库文档。切分后的内容会经过 embedding，然后写入 pgvector 进行检索。",
    },
]

def split_text(text:str)->list[str]:
  return [part.strip() for part in text.split("。")if part.strip()]

chunks=[]

for document in documents:
  for index,content in enumerate(split_text(document["text"])):
    chunks.append(
      {
      "chunk_id": f'{document["id"]}-chunk-{index}',
      "content": content,
      }
    )

print("==chunks sult")
for chunk in chunks:
  print(f'{chunk["chunk_id"]}:{chunk["content"]}')

def tokenize(text:str)->list[str]:
  text =text.lower()
  return re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+",text)

vocabulary=[]

for chunk in chunks:
  tokens=tokenize(chunk["content"])

  for token in tokens:
    if token not in vocabulary:
      vocabulary.append(token)
print("\n=== 词表 ===")
print(vocabulary)
print("词表大小：", len(vocabulary))

token_to_index = {}

for index, token in enumerate(vocabulary):
    token_to_index[token] = index


def text_to_vector(text: str) -> list[int]:
    vector = [0] * len(vocabulary)

    for token in tokenize(text):
      if token in token_to_index:
        index = token_to_index[token]
        vector[index] += 1

    return vector

def readable_vector(vector: list[int]) -> dict[str, int]:
    result = {}

    for index, value in enumerate(vector):
        if value > 0:
            result[vocabulary[index]] = value

    return result


print("\n=== Chunk 向量 ===")

for chunk in chunks:
    vector = text_to_vector(chunk["content"])
    chunk["vector"] = vector

    print(chunk["chunk_id"])
    print(readable_vector(vector))
    
def cosine_similarity(vector_a: list[int], vector_b: list[int]) -> float:
    dot_product = 0
    squared_sum_a = 0
    squared_sum_b = 0

    for value_a, value_b in zip(vector_a, vector_b):
        dot_product += value_a * value_b
        squared_sum_a += value_a * value_a
        squared_sum_b += value_b * value_b

    if squared_sum_a == 0 or squared_sum_b == 0:
        return 0.0

    return dot_product / ((squared_sum_a ** 0.5) * (squared_sum_b ** 0.5))
def search(query: str, top_k: int = 3) -> list[dict]:
    query_vector = text_to_vector(query)
    results = []

    for chunk in chunks:
        score = cosine_similarity(query_vector, chunk["vector"])

        results.append(
            {
                "chunk": chunk,
                "score": score,
            }
        )

    results.sort(key=lambda result: result["score"], reverse=True)

    return results[:top_k]


query = input("\n请输入问题：").strip()

if not query:
    query = "如何做向量相似度检索"
    print("未输入问题，使用默认问题：", query)
top_k = 3
top_results = search(query, top_k)

print("\n=== RAG 检索结果 ===")
print("输入：", query)
print("Top-K：", top_k)

for rank, result in enumerate(top_results, start=1):
    chunk = result["chunk"]
    print(f"\nTop {rank}")
    print("chunk_id：", chunk["chunk_id"])
    print("相似度：", round(result["score"], 4))
    print("文本：", chunk["content"])

def build_context(results: list[dict]) -> str:
    lines = []

    for rank, result in enumerate(results, start=1):
        content = result["chunk"]["content"]
        lines.append(f"资料 {rank}：{content}")

    return "\n".join(lines)


context = build_context(top_results)

prompt = f"""请只根据下面的资料回答问题。

资料：
{context}

问题：
{query}
"""

print("\n=== 给模型的增强 Prompt ===")
print(prompt)

def generate_answer(prompt: str) -> str:
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        raise RuntimeError("未读取到 DEEPSEEK_API_KEY，请先在 PowerShell 中配置。")

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个严谨的助手。只能根据用户提供的资料回答；资料不足时请明确说明。",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
        "max_tokens": 500,
    }

    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    api_request = request.Request(
        url=f"{base_url}/chat/completions",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with request.urlopen(api_request, timeout=60) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    return response_data["choices"][0]["message"]["content"].strip()


answer = generate_answer(prompt)

print("\n=== 最终输出 ===")
print(answer)