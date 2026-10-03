/** Time-aware greeting for the account page, modeled on Claude's rotating
 *  hello messages. Entries mix Chinese and English; `{name}` is replaced
 *  with the user's name, and name-entries are skipped when no name is set.
 *  The caller's local timezone decides the period and weekday. */

type Period = 'morning' | 'afternoon' | 'evening' | 'night'

interface Greeting {
  text: string
  period: Period | 'any'
  /** 0 = Sunday … 6 = Saturday; undefined = any weekday */
  day?: number
}

const GREETINGS: Greeting[] = [
  // morning (5–12)
  { text: '早上好', period: 'morning' },
  { text: '早上好，{name}', period: 'morning' },
  { text: 'Good morning', period: 'morning' },
  { text: 'Good morning, {name}', period: 'morning' },
  { text: '睡得好吗，{name}', period: 'morning' },
  // afternoon (12–18)
  { text: '下午好', period: 'afternoon' },
  { text: '下午好，{name}', period: 'afternoon' },
  { text: 'Good afternoon', period: 'afternoon' },
  { text: 'Good afternoon, {name}', period: 'afternoon' },
  { text: '今天过得怎么样', period: 'afternoon' },
  { text: '今天过得怎么样，{name}', period: 'afternoon' },
  { text: 'How was your day, {name}?', period: 'afternoon' },
  // evening (18–23)
  { text: '晚上好', period: 'evening' },
  { text: '晚上好，{name}', period: 'evening' },
  { text: 'Good evening', period: 'evening' },
  { text: 'Good evening, {name}', period: 'evening' },
  { text: '今天辛苦了，{name}', period: 'evening' },
  // night (23–5)
  { text: '夜深了', period: 'night' },
  { text: '夜深了，{name}', period: 'night' },
  { text: 'Hello, night owl', period: 'night' },
  { text: '夜猫子你好，{name}', period: 'night' },
  { text: '还在忙吗，{name}', period: 'night' },
  // any time
  { text: '你好', period: 'any' },
  { text: '你好，{name}', period: 'any' },
  { text: '欢迎回来', period: 'any' },
  { text: '欢迎回来，{name}', period: 'any' },
  { text: '{name}，欢迎回来', period: 'any' },
  { text: 'Hey there', period: 'any' },
  { text: 'Hey there, {name}', period: 'any' },
  { text: 'How’s it going?', period: 'any' },
  { text: 'How’s it going, {name}?', period: 'any' },
  { text: 'What’s on your mind?', period: 'any' },
  { text: 'What’s on your mind, {name}?', period: 'any' },
  { text: '最近怎么样，{name}', period: 'any' },
  { text: '有什么新想法吗，{name}', period: 'any' },
  // Monday
  { text: '周一快乐', period: 'any', day: 1 },
  { text: '周一快乐，{name}', period: 'any', day: 1 },
  { text: 'Happy Monday', period: 'any', day: 1 },
  { text: 'Happy Monday, {name}', period: 'any', day: 1 },
  { text: '新的一周开始了，{name}', period: 'any', day: 1 },
  // Tuesday
  { text: '周二快乐', period: 'any', day: 2 },
  { text: 'Happy Tuesday', period: 'any', day: 2 },
  { text: 'Happy Tuesday, {name}', period: 'any', day: 2 },
  // Wednesday
  { text: '周三快乐', period: 'any', day: 3 },
  { text: 'Happy Wednesday', period: 'any', day: 3 },
  { text: 'Happy Wednesday, {name}', period: 'any', day: 3 },
  { text: '一周过半了，{name}', period: 'any', day: 3 },
  // Thursday
  { text: '周四快乐', period: 'any', day: 4 },
  { text: 'Happy Thursday', period: 'any', day: 4 },
  { text: 'Happy Thursday, {name}', period: 'any', day: 4 },
  // Friday
  { text: '周五快乐', period: 'any', day: 5 },
  { text: '周五快乐，{name}', period: 'any', day: 5 },
  { text: 'Happy Friday', period: 'any', day: 5 },
  { text: 'Happy Friday, {name}', period: 'any', day: 5 },
  { text: 'That Friday feeling', period: 'any', day: 5 },
  { text: '周末快到了，{name}', period: 'any', day: 5 },
  // Saturday
  { text: '周六快乐', period: 'any', day: 6 },
  { text: '周六快乐，{name}', period: 'any', day: 6 },
  { text: 'Happy Saturday, {name}', period: 'any', day: 6 },
  { text: 'Welcome to the weekend', period: 'any', day: 6 },
  { text: 'Welcome to the weekend, {name}', period: 'any', day: 6 },
  // Sunday
  { text: '周日快乐', period: 'any', day: 0 },
  { text: '周日快乐，{name}', period: 'any', day: 0 },
  { text: 'Happy Sunday', period: 'any', day: 0 },
  { text: 'Happy Sunday, {name}', period: 'any', day: 0 },
  { text: 'Sunday session, {name}?', period: 'any', day: 0 },
  { text: '享受周末的尾巴，{name}', period: 'any', day: 0 },
]

function periodOf(hour: number): Period {
  if (hour >= 5 && hour < 12) return 'morning'
  if (hour >= 12 && hour < 18) return 'afternoon'
  if (hour >= 18 && hour < 23) return 'evening'
  return 'night'
}

function candidates(name: string, now: Date): Greeting[] {
  const period = periodOf(now.getHours())
  const day = now.getDay()
  return GREETINGS.filter(
    (g) =>
      (g.period === period || g.period === 'any') &&
      (g.day === undefined || g.day === day) &&
      (name !== '' || !g.text.includes('{name}'))
  )
}

/** Pick a greeting for the moment. `rand` defaults to Math.random; pass a
 *  fixed value in tests. */
export function pickGreeting(
  name: string,
  now: Date = new Date(),
  rand: () => number = Math.random
): string {
  const pool = candidates(name.trim(), now)
  const g = pool[Math.min(pool.length - 1, Math.floor(rand() * pool.length))]
  return (g?.text ?? '你好').replaceAll('{name}', name.trim())
}
