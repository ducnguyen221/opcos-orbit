from server import security

# TestClient của Starlette dùng Host "testserver" — chỉ cho phép trong môi trường test.
security.EXTRA_HOSTS.add("testserver")
