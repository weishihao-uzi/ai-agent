import json,os
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()
base_url="https://api.deepseek.com"
client=OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"],base_url=base_url)
model="deepseek-chat"
SYSTEM_PROMPT = """你是面试助手，需要面试时按照 get_mock_resume再调用 get_mock_time再调用 get_mock_weather最后调用 get_mock_choice,得出什么时间去面试和简历的基本信息
"""


def get_mock_resume(resume_id:int)->dict:
  if resume_id!=1:
    return {"error": f"简历 {resume_id} 不存在，请检查 ID"}
  return {
    "resume_id":1,
    "user_id":1,
    "target_position":"ai应用开发工程师",
    "parsed_resume":{
      "name":"wlw",
      "education":"jmsu",
      "skills":["fastapi","rag","agent","harness"],
      "projects":["ai-interview-agent","agent-with-event-trgger"],
      
    }
  }
def get_mock_time():
  return {"datetime": "2025-09-13T05:18:47"}
def get_mock_weather(city:str,time:str):
  date=time.split("T")[0]   # '2025-09-13'
  if "北京" not in city and "beijing" not in city.lower():
    return {"error": f"暂只支持查询北京的天气，收到的是: {city}"}
  if date=="2025-09-13":
    return {"weather": "多云","time":"2025-09-13"}
  if date=="2025-09-14":
    return {"weather": "晴","time":"2025-09-14"}
  if date=="2025-09-15":
    return {"weather": "有雨","time":"2025-09-15"}
  return {"error": f"暂只支持查询 2025-09-13 / 2025-09-14 / 2025-09-15 的天气，收到的是: {time}"}
def get_mock_choice(resume:str,weather:str):
  if weather=="有雨":
    return {"choice":"不去面试","resume":None}
  if weather=="晴":
    return {"choice":"去面试","resume":resume}
  if weather=="多云":
    return {"choice":"去面试","resume":resume}
  return{"error":"unknowed weather"}
TOOLS=[
  {
    "type":"function",
    "function":{
      "name":"get_mock_resume",
      "description":"根据简历 ID 读取候选人的结构化简历信息（技能、教育、项目等），需要简历内容时调用本工具",
      "parameters":{
        "type":"object",
        "properties":{"resume_id":{"type":"integer","description":"简历的数据库 ID，例如 1"}},
        "required":["resume_id"],
      },
    },
  },
  {
    "type":"function",
    "function":{
      "name":"get_mock_time",
      "description":"根据指定time返回时间",
      "parameters":{
        "type":"object",
        "properties":{
                 },
        "required":[],
      },
    },
  },
  {
    "type":"function",
    "function":{
      "name":"get_mock_weather",
      "description":"根据指定weather返回天气",
      "parameters":{
        "type":"object",
        "properties":{
          "time":{"type":"string","description":"“查询日期，格式 YYYY-MM-DD,例如 2025-09-13"},
          "city":{"type":"string","description":"city name,e.g. China/Beijing"},
        },
        "required":["city","time"],
      },
    },
  },
  {
    "type":"function",
    "function":{
      "name":"get_mock_choice",
      "description":"结合get_mock_resume，get_mock_weather2个工具的执行结果，决定哪天什么时间去面试，和面试前的简历基本信息",
      "parameters":{
        "type":"object",
        "properties":{
          "weather":{"type":"string","description":"weathername,e.g.  多云，晴，有雨"},
          "resume":{"type":"integer","description":"get_mock_resume的返回值,格式为字典列表"},
          
                },
        "required":["weather","resume"],
      },
    },
  },
]

def excute_tool(name,argument):
  if name=="get_mock_resume":
    return get_mock_resume(**argument)
  if name=="get_mock_time":
    return get_mock_time()
  if name=="get_mock_weather":
    return get_mock_weather(**argument)
  if name=="get_mock_choice":
    return get_mock_choice(**argument)
  else:
    return None

messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":"简历id是1帮我看下什么时间能去上海面试"}]
max_index=10

index=0
while index<max_index:
  index+=1
  response=client.chat.completions.create(model=model,messages=messages,tools=TOOLS)

  msg=response.choices[0].message
  messages.append(msg.model_dump())

  if not msg.tool_calls:
    print(msg.content)
    print("----------------------------------------")
    print(json.dumps(messages, ensure_ascii=False, indent=2, default=str))
    break
  
  
  for tool_call in msg.tool_calls:
    args=json.loads(tool_call.function.arguments)
    result=excute_tool(tool_call.function.name,args)
    messages.append(
      {
      "role":"tool",
      "tool_call_id":tool_call.id,
      "content":json.dumps(result,ensure_ascii=False)
      }
    )
  
  
    

    
