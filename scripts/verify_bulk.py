
import asyncio
import httpx
import os
import time

API_URL = "http://127.0.0.1:8000/api"

async def create_dummy_files(count=10):
    files = []
    if not os.path.exists("temp_test_files"):
        os.makedirs("temp_test_files")
        
    for i in range(count):
        name = f"test_biodata_{i}.pdf"
        if i % 3 == 0:  # Every 3rd file fails
            name = f"test_fail_biodata_{i}.pdf"
            
        path = os.path.join("temp_test_files", name)
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 mock content")
        files.append((path, name))
    return files

async def verify():
    # 1. Create Files
    files = await create_dummy_files(12)
    print(f"Created {len(files)} test files (4 should fail).")

    # 2. Upload
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Prepare multipart upload
        upload_files = []
        file_objs = []
        for path, name in files:
            f = open(path, "rb")
            file_objs.append(f)
            upload_files.append(("files", (name, f, "application/pdf")))
            
        print("Uploading...")
        start_time = time.time()
        resp = await client.post(f"{API_URL}/upload/async/bulk", files=upload_files)
        print(f"Upload Response: {resp.status_code}")
        
        # Close files
        for f in file_objs:
            f.close()
            
        if resp.status_code != 200:
            print("Upload failed!", resp.text)
            return

        data = resp.json()
        print(f"Queued: {data['queued']}, Total: {data['total']}")
        
        # 3. Monitor
        print("Monitoring progress...")
        for i in range(20): # Wait up to 20s
            await asyncio.sleep(1)
            
            # Check DB count
            r = await client.get(f"{API_URL}/biodata", params={"page_size": 100})
            items = r.json()["items"]
            
            pending = sum(1 for x in items if x['ocr_status'] == 'pending')
            processing = sum(1 for x in items if x['ocr_status'] == 'processing')
            completed = sum(1 for x in items if x['ocr_status'] == 'completed')
            # Failed should be 0 because we delete them!
            failed = sum(1 for x in items if x['ocr_status'] == 'failed')
            
            # Count how many of OUR files are present
            our_files = [x for x in items if "test_" in x['original_filename']]
            our_count = len(our_files)
            
            print(f"T+{i}s: Total={len(items)}, Pending={pending}, Processing={processing}, Completed={completed}, Failed={failed}. (Our Files: {our_count})")
            
            if pending == 0 and processing == 0 and our_count == 8: # 12 - 4 failures = 8
                print("SUCCESS: All processed, failed files removed.")
                break
                
    # Cleanup
    import shutil
    shutil.rmtree("temp_test_files")

if __name__ == "__main__":
    asyncio.run(verify())
