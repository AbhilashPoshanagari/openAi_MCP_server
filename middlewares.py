# from fastmcp.server.middleware import Middleware, MiddlewareContext
# class RawMiddleware(Middleware):
#     async def __call__(self, context: MiddlewareContext, call_next):
#         # This method receives ALL messages regardless of type
#         print(f"Raw middleware processing: {context.method}")
#         result = await call_next(context)
#         print(f"Raw middleware completed: {context.method}")
#         return result