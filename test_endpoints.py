import asyncio
from httpx import AsyncClient
from app.core import security
from app.core.config import settings

async def test_apis():
    token = security.create_access_token(data={"sub": "12345678901", "role": "admin"})
    cookies = {"access_token": f"Bearer {token}"}
    
    async with AsyncClient(base_url="http://localhost:8000") as client:
        r1 = await client.get("/api/admin/participantes", cookies=cookies)
        print("PARTICIPANTES STATUS:", r1.status_code)
        if r1.status_code == 200:
            print("PARTICIPANTES JSON:", r1.json())
            
        r2 = await client.get("/api/admin/usuarios-equipe", cookies=cookies)
        print("EQUIPE STATUS:", r2.status_code)
        if r2.status_code == 200:
            print("EQUIPE JSON:", r2.json())

if __name__ == "__main__":
    asyncio.run(test_apis())
