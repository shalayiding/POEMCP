from mcp.server.fastmcp import FastMCP

from scrapers.player.gems import get_gem_detail, search_gem
from scrapers.player.items import get_item_detail, search_item
from scrapers.player.passives import get_passive_detail, search_passive
from scrapers.mods.item_mods import search_mods
from scrapers.env import env_detail, env_search
from scrapers.economy import currency_overview, price_check
from scrapers.wiki import fetch_wiki_page
from scrapers.player.pob import parse_pob

mcp = FastMCP("PoeMCP")

# --- Player domain ---
mcp.tool()(search_gem)
mcp.tool()(get_gem_detail)
mcp.tool()(search_item)
mcp.tool()(get_item_detail)
mcp.tool()(search_passive)
mcp.tool()(get_passive_detail)

# --- Mods domain ---
mcp.tool()(search_mods)

# --- Env domain ---
mcp.tool()(env_search)
mcp.tool()(env_detail)

# --- Economy domain ---
mcp.tool()(price_check)
mcp.tool()(currency_overview)

# --- Universal ---
mcp.tool()(fetch_wiki_page)

# --- PoB ---
mcp.tool()(parse_pob)

def main():
    mcp.run()

if __name__ == "__main__":
    main()
