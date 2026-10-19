import brand from '../assets/icons/brand.svg'
import dashboard from '../assets/icons/dashboard.svg'
import bot from '../assets/icons/bot.svg'
import messages from '../assets/icons/messages.svg'
import plus from '../assets/icons/plus.svg'
import emptyBot from '../assets/icons/empty-bot.svg'
import sliders from '../assets/icons/sliders.svg'
import files from '../assets/icons/files.svg'
import sparkles from '../assets/icons/sparkles.svg'
import menu from '../assets/icons/menu.svg'
import homeMobile from '../assets/icons/home-mobile.svg'
import botMobile from '../assets/icons/bot-mobile.svg'
import sparklesMobile from '../assets/icons/sparkles-mobile.svg'
import messagesMobile from '../assets/icons/messages-mobile.svg'

const icons = { brand, dashboard, bot, messages, plus, emptyBot, sliders, files,
  sparkles, menu, homeMobile, botMobile, sparklesMobile, messagesMobile }
export type IconName = keyof typeof icons

// Intrinsic SVG dimensions match each Figma slot; do not globally resize icons.
export function Icon({ name }: { name: IconName }) {
  return <img src={icons[name]} alt="" aria-hidden="true" />
}
