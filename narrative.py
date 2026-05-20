import feedparser
import urllib.parse
import json
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum


class Severity(Enum):
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    INFO = 1


@dataclass
class SeverityMetrics:
    """Quantified severity metrics in pricing-relevant units"""
    # Supply/Demand impacts
    supply_loss_mbd: Optional[float] = None  # Million barrels/day (for oil)
    supply_loss_bcf: Optional[float] = None  # Billion cubic feet/day (for gas)
    supply_loss_tonnes: Optional[float] = None  # Tonnes/day (for metals/agricultural)
    demand_change_pct: Optional[float] = None  # % change in demand

    # Shipping/Logistics
    shipping_disruption_pct: Optional[float] = None  # % capacity reduction
    insurance_multiplier: Optional[float] = None  # e.g., 1.5x = 50% increase

    # Duration
    duration_days: Optional[int] = None  # Estimated duration in days
    duration_range: Optional[str] = None  # e.g., "7-14 days"

    # Confidence
    confidence: float = 0.5  # 0.0 to 1.0
    confidence_rationale: str = ""


class AssetType(Enum):
    CRUDE_OIL = "Crude Oil"
    NATURAL_GAS = "Natural Gas"
    PRECIOUS_METALS = "Precious Metals"
    BASE_METALS = "Base Metals"
    AGRICULTURAL = "Agricultural"
    ENERGY = "Energy"
    SOFT_COMMODITIES = "Soft Commodities"


# Asset sub-classes mapping
ASSET_SUBCLASSES = {
    AssetType.CRUDE_OIL: ["WTI", "Brent", "Dubai", "OPEC Basket", "Urals"],
    AssetType.NATURAL_GAS: ["US Natural Gas", "EU TTF", "UK NBP", "Asia LNG", "Henry Hub"],
    AssetType.PRECIOUS_METALS: ["Gold", "Silver", "Platinum", "Palladium"],
    AssetType.BASE_METALS: ["Copper", "Aluminum", "Zinc", "Nickel", "Lead", "Tin"],
    AssetType.AGRICULTURAL: ["Wheat", "Corn", "Soybeans", "Rice", "Cotton", "Sugar"],
    AssetType.SOFT_COMMODITIES: ["Coffee", "Cocoa", "Orange Juice"],
}


@dataclass
class RawPost:
    """Represents a raw news article or social media post"""
    source_platform: str  # e.g., "Google News", "X", "Truth Social", "Reuters RSS"
    source_name: str      # e.g., "@realDonaldTrump", "Reuters", "local_user_123"
    title: str
    content: str
    link: str
    published: str
    author: Optional[str] = None
    location: Optional[str] = None


@dataclass
class ClassifiedPost:
    """A post that has been filtered and classified"""
    raw_post: RawPost
    is_commodity_related: bool
    relevance_score: float  # 0.0 to 1.0
    reliability_score: float  # 0.0 to 1.0
    asset_types: List[str] = field(default_factory=list)
    asset_subclasses: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    severity: str = "INFO"
    actors: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    duration_estimate: Optional[str] = None


@dataclass
class EventGroup:
    """A group of related posts about the same event"""
    event_name: str
    event_type: str
    severity: str
    severity_metrics: Optional[SeverityMetrics] = None
    asset_types: List[str] = field(default_factory=list)
    asset_subclasses: List[str] = field(default_factory=list)
    actors: List[str] = field(default_factory=list)
    targets: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    posts: List[ClassifiedPost] = field(default_factory=list)
    summary: str = ""
    first_reported: str = ""
    last_updated: str = ""


# --- NEWS SOURCE FETCHERS ---
class NewsFetcher:
    """Base class for fetching news from various sources"""

    @staticmethod
    def fetch_google_news(query: str, time_window: str = "4h") -> List[RawPost]:
        """Fetches news from Google News RSS"""
        encoded_query = urllib.parse.quote(f'{query} when:{time_window}')
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

        feed = feedparser.parse(rss_url)
        posts = []

        for entry in feed.entries:
            posts.append(RawPost(
                source_platform="Google News",
                source_name=entry.source.title if 'source' in entry else "Unknown",
                title=entry.title,
                content=entry.get('summary', entry.title),
                link=entry.link,
                published=entry.published,
            ))
        return posts

    @staticmethod
    def fetch_oilprice_news() -> List[RawPost]:
        """Fetches energy news from OilPrice.com RSS"""
        rss_url = "https://oilprice.com/rss/main"
        try:
            feed = feedparser.parse(rss_url)
            posts = []

            for entry in feed.entries[:15]:
                posts.append(RawPost(
                    source_platform="OilPrice.com",
                    source_name="OilPrice",
                    title=entry.title,
                    content=entry.get('summary', entry.title),
                    link=entry.link,
                    published=entry.published if 'published' in entry else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                ))
            return posts
        except Exception as e:
            print(f"  [Warning] Failed to fetch OilPrice.com: {e}")
            return []

    @staticmethod
    def fetch_reuters_commodities() -> List[RawPost]:
        """Fetches Reuters commodities news via RSS"""
        rss_url = "https://www.reutersagency.com/feed/?taxonomy=best-sectors&post_type=best"
        feed = feedparser.parse(rss_url)
        posts = []

        for entry in feed.entries[:15]:
            posts.append(RawPost(
                source_platform="Reuters",
                source_name="Reuters Commodities",
                title=entry.title,
                content=entry.get('summary', entry.title),
                link=entry.link,
                published=entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            ))
        return posts

    @staticmethod
    def fetch_investing_com_news() -> List[RawPost]:
        """Fetches commodities news from Investing.com RSS"""
        rss_url = "https://www.investing.com/rss/news_14.rss"
        try:
            feed = feedparser.parse(rss_url)
            posts = []

            for entry in feed.entries[:15]:
                posts.append(RawPost(
                    source_platform="Investing.com",
                    source_name="Investing.com Commodities",
                    title=entry.title,
                    content=entry.get('summary', entry.title),
                    link=entry.link,
                    published=entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                ))
            return posts
        except Exception as e:
            print(f"  [Warning] Failed to fetch Investing.com: {e}")
            return []

    @staticmethod
    def fetch_yahoo_finance(asset_class: str) -> List[RawPost]:
        """Fetches news from Yahoo Finance RSS"""
        rss_urls = {
            "Commodities": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL=F,GC=F,HG=F,BZ=F",
            "Equities": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,^DJI,^STOXX50E",
            "Interest Rates": "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^TNX,^IRX,^TYX"
        }
        try:
            feed = feedparser.parse(rss_urls.get(asset_class, rss_urls["Commodities"]), agent="Mozilla/5.0")
            posts = []
            for entry in feed.entries[:10]:
                posts.append(RawPost(
                    source_platform="Yahoo Finance",
                    source_name="Yahoo Finance",
                    title=entry.title,
                    content=entry.get('summary', entry.title),
                    link=getattr(entry, 'link', '#'),
                    published=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                ))
            return posts
        except:
            return []

    @staticmethod
    def fetch_government_releases() -> List[RawPost]:
        """Fetches press releases from G7 + China + Russia governments"""
        posts = []

        # Government RSS feeds
        gov_sources = [
            # USA
            ("https://www.whitehouse.gov/feed/", "White House", "USA"),
            ("https://www.state.gov/rss-feed/press-releases/feed/", "US State Dept", "USA"),
            ("https://www.energy.gov/rss.xml", "US Dept of Energy", "USA"),
            ("https://www.treasury.gov/press-center/press-releases/Pages/rss.aspx", "US Treasury", "USA"),

            # UK
            ("https://www.gov.uk/government/announcements.atom", "UK Government", "UK"),

            # EU
            ("https://ec.europa.eu/commission/presscorner/api/rss", "European Commission", "EU"),

            # Germany
            ("https://www.bundesregierung.de/breg-de/service/rss-feeds", "German Government", "Germany"),

            # France
            ("https://www.gouvernement.fr/rss/actualites.xml", "French Government", "France"),

            # Japan
            ("https://www.mofa.go.jp/rss/press.rdf", "Japan MOFA", "Japan"),

            # Canada
            ("https://www.canada.ca/en/news/web-feeds.html", "Canada Government", "Canada"),

            # Russia (TASS English)
            ("https://tass.com/rss/v2.xml", "TASS", "Russia"),

            # China (Xinhua English)
            ("http://www.news.cn/english/rss/worldrss.xml", "Xinhua", "China"),
        ]

        for rss_url, source_name, country in gov_sources:
            try:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries[:10]:
                    posts.append(RawPost(
                        source_platform="Government",
                        source_name=f"{source_name} ({country})",
                        title=entry.get('title', ''),
                        content=entry.get('summary', entry.get('title', '')),
                        link=entry.get('link', ''),
                        published=entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                        location=country,
                    ))
            except Exception as e:
                print(f"  [Warning] Failed to fetch {source_name}: {e}")

        return posts

    @staticmethod
    def fetch_central_bank_releases() -> List[RawPost]:
        """Fetches press releases from major central banks"""
        posts = []

        cb_sources = [
            # Federal Reserve
            ("https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", "USA"),

            # ECB
            ("https://www.ecb.europa.eu/rss/press.html", "ECB", "EU"),

            # Bank of England
            ("https://www.bankofengland.co.uk/rss/news", "Bank of England", "UK"),

            # Bank of Japan
            ("https://www.boj.or.jp/en/rss/whatsnew.xml", "Bank of Japan", "Japan"),

            # Bank of Canada
            ("https://www.bankofcanada.ca/feed/", "Bank of Canada", "Canada"),

            # People's Bank of China (English news)
            ("http://www.pbc.gov.cn/english/rss/rssxml/130721e.xml", "PBOC", "China"),

            # Central Bank of Russia
            ("https://www.cbr.ru/eng/rss/RssPress", "Bank of Russia", "Russia"),
        ]

        for rss_url, source_name, country in cb_sources:
            try:
                feed = feedparser.parse(rss_url)
                for entry in feed.entries[:10]:
                    posts.append(RawPost(
                        source_platform="Central Bank",
                        source_name=f"{source_name} ({country})",
                        title=entry.get('title', ''),
                        content=entry.get('summary', entry.get('title', '')),
                        link=entry.get('link', ''),
                        published=entry.get('published', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                        location=country,
                    ))
            except Exception as e:
                print(f"  [Warning] Failed to fetch {source_name}: {e}")

        return posts


# --- CLASSIFICATION AND FILTERING ---
class CommodityClassifier:
    """Uses Gemini to classify and filter commodity-related posts"""

    COMMODITY_KEYWORDS = [
        "oil", "crude", "brent", "wti", "opec", "petroleum", "gasoline", "diesel",
        "natural gas", "lng", "pipeline", "refinery", "energy",
        "gold", "silver", "copper", "aluminum", "zinc", "nickel", "platinum", "palladium",
        "iron ore", "steel", "mining",
        "wheat", "corn", "soybeans", "rice", "cotton", "sugar", "coffee", "cocoa",
        "grain", "crop", "harvest", "agriculture",
        "sanctions", "embargo", "blockade", "tariff", "trade war", "supply chain",
        "shipping", "strait", "suez", "hormuz", "port", "export ban",
        "drought", "flood", "hurricane", "freeze", "wildfire",
        "stock", "equity", "index", "dow", "nasdaq", "s&p", "ftse", "dax", "nikkei",
        "interest rate", "federal reserve", "ecb", "inflation", "bond", "yield", "treasury"
    ]

    HIGH_RELIABILITY_SOURCES = [
        "Reuters", "Bloomberg", "Financial Times", "Wall Street Journal",
        "OilPrice", "Investing.com", "CNBC", "BBC", "AP News",
        "White House", "US State Dept", "US Treasury", "Federal Reserve",
        "ECB", "Bank of England", "European Commission", "Xinhua", "TASS",
        "PBOC", "Bank of Japan", "Bank of Canada", "Bank of Russia"
    ]

    @staticmethod
    def quick_filter(post: RawPost) -> bool:
        """Quick keyword-based pre-filter"""
        text = (post.title + " " + post.content).lower()
        return any(keyword in text for keyword in CommodityClassifier.COMMODITY_KEYWORDS)

    @staticmethod
    def calculate_reliability(post: RawPost) -> float:
        """Calculate reliability score based on source"""
        score = 0.5
        if any(src.lower() in post.source_name.lower() for src in CommodityClassifier.HIGH_RELIABILITY_SOURCES):
            score += 0.3
        return min(max(score, 0.0), 1.0)

    @staticmethod
    def classify_with_ai(post: RawPost, ai_model) -> Optional[ClassifiedPost]:
        """Uses Gemini to classify a post"""

        prompt = f"""
        You are an expert financial market analyst. Analyze this news/post and determine if it's relevant to commodity/equity/Interest rate markets.

        Source: {post.source_platform} - {post.source_name}
        Title: {post.title}
        Content: {post.content}

        Return ONLY a valid JSON object:
        {{
            "is_relevant": true/false,
            "relevance_score": 0.0-1.0 (how directly relevant to commodity/equity/IR),
            "asset_types": ["Crude Oil", "Natural Gas", "Precious Metals", "Base Metals", "Agricultural", "Energy", "Soft Commodities", "Equities", "Interest Rates"],
            "asset_subclasses": ["WTI", "Brent", "Gold", ""S&P 500", etc. - specific commodity/equity],
            "events": ["brief event description - e.g., 'OPEC production cut', 'Russia-Ukraine conflict'"],
            "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO",
            "actors": ["entities causing the event"],
            "targets": ["entities affected"],
            "regions": ["geographic regions involved"],
            "duration_estimate": "immediate" | "short-term" | "medium-term" | "long-term" | null
        }}
        """

        try:
            response = ai_model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]

            data = json.loads(text)

            return ClassifiedPost(
                raw_post=post,
                is_commodity_related=data.get('is_relevant', False),
                relevance_score=data.get('relevance_score', 0.0),
                reliability_score=CommodityClassifier.calculate_reliability(post),
                asset_types=data.get('asset_types', []),
                asset_subclasses=data.get('asset_subclasses', []),
                events=data.get('events', []),
                severity=data.get('severity', 'INFO'),
                actors=data.get('actors', []),
                targets=data.get('targets', []),
                regions=data.get('regions', []),
                duration_estimate=data.get('duration_estimate'),
            )

        except Exception as e:
            print(f"Error classifying post: {e}")
            return None


# --- EVENT GROUPING ---
class EventGrouper:
    """Groups classified posts by event/conflict"""

    @staticmethod
    def group_posts(posts: List[ClassifiedPost], ai_model) -> List[EventGroup]:
        """Group posts by related events using Gemini"""

        if not posts:
            return []

        # Prepare post summaries for grouping
        post_summaries = []
        for i, post in enumerate(posts):
            post_summaries.append({
                "id": i,
                "title": post.raw_post.title,
                "content": post.raw_post.content[:200],
                "events": post.events,
                "asset_types": post.asset_types,
                "regions": post.regions,
                "actors": post.actors,
                "severity": post.severity
            })

        prompt = f"""
        You are an expert commodity/equity/Interest Rates market analyst. Group these news items by the underlying event/conflict and provide quantified severity metrics for pricing models.

        Posts:
        {json.dumps(post_summaries, indent=2)}

        Return ONLY a valid JSON array of event groups with quantified metrics (max 10 groups):
        [
            {{
                "event_name": "Descriptive name for the event",
                "event_type": "Geopolitical Conflict" | "Supply Disruption" | "Policy Change" | "Weather Event" | "Market Movement" | "Trade Dispute" | "Economic Data" | "Central Bank Action",
                "post_ids": [list of post IDs that belong to this event],
                "summary": "Brief summary of the event and its commodity/Equity market implications",
                "severity_metrics": {{
                    "supply_loss_mbd": null or float (million barrels/day - for oil),
                    "supply_loss_bcf": null or float (billion cubic feet/day - for gas),
                    "supply_loss_tonnes": null or float (tonnes/day - for metals/agricultural),
                    "demand_change_pct": null or float (% change, negative for reduction),
                    "shipping_disruption_pct": null or float (% capacity reduction, 0-100),
                    "insurance_multiplier": null or float (e.g., 1.5 means 50% premium increase),
                    "duration_days": null or int (estimated duration),
                    "duration_range": null or string (e.g., "7-14 days", "30-90 days"),
                    "confidence": 0.0-1.0 (how confident are you in these estimates),
                    "confidence_rationale": "Brief explanation of confidence level"
                }}
            }}
        ]

        IMPORTANT GUIDELINES for severity_metrics:
        - For OIL supply disruptions: estimate in million barrels/day (mbd). Examples:
          - Major OPEC cut: 1.0-2.0 mbd
          - Single country outage: 0.3-1.5 mbd
          - Refinery issue: 0.1-0.5 mbd
        - For GAS disruptions: estimate in billion cubic feet/day (bcf)
        - For SHIPPING disruptions: estimate % of capacity affected and insurance multiplier
          - Strait of Hormuz threat: 30-50% capacity, 2.0-3.0x insurance
          - Red Sea/Suez disruption: 10-20% capacity, 1.5-2.0x insurance
        - For DEMAND changes: estimate % change (negative for reduction)
        - For DURATION: estimate in days with a range if uncertain
        - CONFIDENCE should reflect:
          - 0.8-1.0: Official announcements, confirmed data
          - 0.6-0.8: Multiple reliable sources, historical precedent
          - 0.4-0.6: Single source, some uncertainty
          - 0.2-0.4: Speculation, unverified reports
          - 0.0-0.2: Rumors, highly uncertain
        - For events without clear supply/demand impact (for example, Equity/Interest Rates related, use null for those metrics and provide a qualitative summary in the "summary" field.

        Only include metrics relevant to the specific event. Use null for non-applicable metrics.
        """

        try:
            response = ai_model.generate_content(prompt)
            text = response.text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            groups_data = json.loads(text)

            event_groups = []
            for group_data in groups_data[:10]:
                group_posts = [posts[i] for i in group_data.get('post_ids', []) if i < len(posts)]

                if not group_posts:
                    continue

                # Aggregate attributes from all posts in the group
                all_asset_types = list(set(at for p in group_posts for at in p.asset_types))
                all_asset_subclasses = list(set(asc for p in group_posts for asc in p.asset_subclasses))
                all_actors = list(set(a for p in group_posts for a in p.actors))
                all_targets = list(set(t for p in group_posts for t in p.targets))
                all_regions = list(set(r for p in group_posts for r in p.regions))

                # Get highest severity
                severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
                severities = [p.severity for p in group_posts]
                highest_severity = min(severities, key=lambda x: severity_order.index(x) if x in severity_order else 5)

                # Get time range
                published_dates = [p.raw_post.published for p in group_posts]

                # Parse severity metrics
                metrics_data = group_data.get('severity_metrics', {})
                severity_metrics = SeverityMetrics(
                    supply_loss_mbd=metrics_data.get('supply_loss_mbd'),
                    supply_loss_bcf=metrics_data.get('supply_loss_bcf'),
                    supply_loss_tonnes=metrics_data.get('supply_loss_tonnes'),
                    demand_change_pct=metrics_data.get('demand_change_pct'),
                    shipping_disruption_pct=metrics_data.get('shipping_disruption_pct'),
                    insurance_multiplier=metrics_data.get('insurance_multiplier'),
                    duration_days=metrics_data.get('duration_days'),
                    duration_range=metrics_data.get('duration_range'),
                    confidence=metrics_data.get('confidence', 0.5),
                    confidence_rationale=metrics_data.get('confidence_rationale', ''),
                )

                event_groups.append(EventGroup(
                    event_name=group_data['event_name'],
                    event_type=group_data['event_type'],
                    severity=highest_severity,
                    severity_metrics=severity_metrics,
                    asset_types=all_asset_types,
                    asset_subclasses=all_asset_subclasses,
                    actors=all_actors,
                    targets=all_targets,
                    regions=all_regions,
                    posts=group_posts,
                    summary=group_data.get('summary', ''),
                    first_reported=min(published_dates) if published_dates else "",
                    last_updated=max(published_dates) if published_dates else "",
                ))
            # Sort by severity
            severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3, 'INFO': 4}
            event_groups.sort(key=lambda x: severity_order.get(x.severity, 5))

            return event_groups

        except Exception as e:
            print(f"Error grouping events: {e}")
            return []
