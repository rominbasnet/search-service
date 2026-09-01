from fastapi import FastAPI

from app.es_client import close_es
from app.routers import search, products, feedback

app = FastAPI(
    title="Search-as-a-Service",
    description="Elasticsearch relevance engineering: synonyms, typo "
    "tolerance, business-logic boosting, click-through feedback loop.",
    version="1.0.0",
)

app.include_router(search.router)
app.include_router(products.router)
app.include_router(feedback.router)


@app.on_event("shutdown")
async def shutdown():
    await close_es()


@app.get("/health")
async def health():
    return {"status": "ok"}
