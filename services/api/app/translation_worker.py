from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


LANGUAGE_NAMES = {"fr":"French","en":"English","es":"Spanish","pt":"Portuguese","de":"German","ja":"Japanese","ko":"Korean","zh":"Chinese","ar":"Arabic","it":"Italian"}
NLLB_CODES = {"fr":"fra_Latn","en":"eng_Latn","es":"spa_Latn","pt":"por_Latn","de":"deu_Latn","ja":"jpn_Jpan","ko":"kor_Hang","zh":"zho_Hans","ar":"arb_Arab","it":"ita_Latn"}


def run(manifest:dict[str,Any],payload:dict[str,Any])->dict[str,Any]:
    runtime=manifest.get("runtime")
    if runtime=="llama_cpp":
        return run_llama(manifest,payload)
    if runtime=="ctranslate2":
        return run_ctranslate(manifest,payload)
    if runtime=="transformers":
        return run_transformers(manifest,payload,onnx=False)
    if runtime=="onnx":
        return run_transformers(manifest,payload,onnx=True)
    raise RuntimeError(f"Unsupported translation runtime: {runtime}")


def run_llama(manifest:dict[str,Any],payload:dict[str,Any])->dict[str,Any]:
    from llama_cpp import Llama
    model=Llama(model_path=str(manifest["model_path"]),n_ctx=4096,n_batch=256,n_gpu_layers=-1,verbose=False)
    source=LANGUAGE_NAMES.get(payload.get("source_language"),payload.get("source_language") or "the source language")
    target=LANGUAGE_NAMES.get(payload.get("target_language"),payload.get("target_language") or "French")
    translations=[]
    for item in payload.get("segments",[]):
        text=str(item.get("text","")).strip()
        if not text:
            translations.append({"id":item.get("id"),"text":""});continue
        response=model.create_chat_completion(messages=[
            {"role":"system","content":f"You are a professional audiovisual translator. Translate from {source} to {target}. Preserve names and meaning. Return only the translated sentence, without notes or quotation marks."},
            {"role":"user","content":text},
        ],temperature=0.15,top_p=0.9,max_tokens=max(96,min(700,len(text)*3)))
        translated=str(response["choices"][0]["message"]["content"]).strip()
        translations.append({"id":item.get("id"),"text":translated})
    return {"translations":translations}


def run_ctranslate(manifest:dict[str,Any],payload:dict[str,Any])->dict[str,Any]:
    import ctranslate2
    from transformers import AutoTokenizer
    model_path=Path(str(manifest["model_path"]))
    tokenizer=AutoTokenizer.from_pretrained(model_path)
    translator=ctranslate2.Translator(str(model_path),device="auto",compute_type="auto")
    source_code=NLLB_CODES.get(payload.get("source_language","en"),"eng_Latn")
    target_code=NLLB_CODES.get(payload.get("target_language","fr"),"fra_Latn")
    tokenizer.src_lang=source_code
    translations=[]
    for item in payload.get("segments",[]):
        text=str(item.get("text","")).strip()
        if not text:
            translations.append({"id":item.get("id"),"text":""});continue
        source_tokens=tokenizer.convert_ids_to_tokens(tokenizer.encode(text))
        target_prefix=[target_code]
        result=translator.translate_batch([source_tokens],target_prefix=[target_prefix],beam_size=4,max_decoding_length=512)[0]
        target_tokens=result.hypotheses[0][1:]
        translated=tokenizer.decode(tokenizer.convert_tokens_to_ids(target_tokens),skip_special_tokens=True).strip()
        translations.append({"id":item.get("id"),"text":translated})
    return {"translations":translations}


def run_transformers(manifest:dict[str,Any],payload:dict[str,Any],onnx:bool)->dict[str,Any]:
    from transformers import AutoTokenizer
    model_path=str(manifest["model_path"])
    tokenizer=AutoTokenizer.from_pretrained(model_path)
    is_seq2seq=bool(getattr(tokenizer,"src_lang",None)) or "nllb" in str(manifest.get("repo_id","")).lower()
    if onnx:
        if is_seq2seq:
            from optimum.onnxruntime import ORTModelForSeq2SeqLM
            model=ORTModelForSeq2SeqLM.from_pretrained(model_path)
        else:
            from optimum.onnxruntime import ORTModelForCausalLM
            model=ORTModelForCausalLM.from_pretrained(model_path)
    else:
        if is_seq2seq:
            from transformers import AutoModelForSeq2SeqLM
            model=AutoModelForSeq2SeqLM.from_pretrained(model_path,device_map="auto",torch_dtype="auto")
        else:
            from transformers import AutoModelForCausalLM
            model=AutoModelForCausalLM.from_pretrained(model_path,device_map="auto",torch_dtype="auto")
    source=LANGUAGE_NAMES.get(payload.get("source_language"),payload.get("source_language") or "the source language")
    target=LANGUAGE_NAMES.get(payload.get("target_language"),payload.get("target_language") or "French")
    translations=[]
    for item in payload.get("segments",[]):
        text=str(item.get("text","")).strip()
        if not text:
            translations.append({"id":item.get("id"),"text":""});continue
        if is_seq2seq:
            source_code=NLLB_CODES.get(payload.get("source_language","en"),"eng_Latn")
            target_code=NLLB_CODES.get(payload.get("target_language","fr"),"fra_Latn")
            tokenizer.src_lang=source_code
            inputs=tokenizer(text,return_tensors="pt")
            if not onnx:
                inputs={key:value.to(model.device) for key,value in inputs.items()}
            generated=model.generate(**inputs,forced_bos_token_id=tokenizer.convert_tokens_to_ids(target_code),max_new_tokens=512)
            translated=tokenizer.batch_decode(generated,skip_special_tokens=True)[0].strip()
        else:
            messages=[{"role":"system","content":f"Translate professionally from {source} to {target}. Return only the translated sentence."},{"role":"user","content":text}]
            prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True) if getattr(tokenizer,"chat_template",None) else f"Translate from {source} to {target}:\n{text}\nTranslation:"
            inputs=tokenizer(prompt,return_tensors="pt")
            if not onnx:
                inputs={key:value.to(model.device) for key,value in inputs.items()}
            generated=model.generate(**inputs,max_new_tokens=max(96,min(700,len(text)*3)),do_sample=False)
            translated=tokenizer.decode(generated[0][inputs["input_ids"].shape[-1]:],skip_special_tokens=True).strip()
        translations.append({"id":item.get("id"),"text":translated})
    return {"translations":translations}


if __name__=="__main__":
    manifest=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    payload=json.load(sys.stdin)
    json.dump(run(manifest,payload),sys.stdout,ensure_ascii=False)
