import { useState } from 'react'
import { Search, Mail, Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import {
  Button,
  Input,
  Textarea,
  Select,
  Checkbox,
  Toggle,
  RadioGroup,
  Slider,
  Badge,
} from '../../components/ui'

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="font-sans text-h2 text-content-primary mb-4">{children}</h2>
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-h4 text-content-secondary mb-3">{title}</h3>
      {children}
    </div>
  )
}

function DemoCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface-card p-6 space-y-4">
      {children}
    </div>
  )
}

// ── Button Gallery ─────────────────────────────────────────────────────────────

function ButtonGallery() {
  return (
    <div>
      <SectionTitle>Button</SectionTitle>
      <DemoCard>
        <SubSection title="Variants">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="outline">Outline</Button>
          </div>
        </SubSection>

        <SubSection title="Sizes">
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
            <Button size="lg">Large</Button>
          </div>
        </SubSection>

        <SubSection title="With Icons">
          <div className="flex flex-wrap items-center gap-3">
            <Button icon={<Plus size={14} />}>Add Item</Button>
            <Button variant="danger" icon={<Trash2 size={14} />}>Delete</Button>
            <Button variant="secondary" icon={<Mail size={14} />}>Send</Button>
          </div>
        </SubSection>

        <SubSection title="Loading">
          <div className="flex flex-wrap items-center gap-3">
            <Button loading>Saving...</Button>
            <Button variant="secondary" loading>Loading</Button>
            <Button variant="danger" loading size="sm">Deleting</Button>
          </div>
        </SubSection>

        <SubSection title="Disabled">
          <div className="flex flex-wrap items-center gap-3">
            <Button disabled>Disabled</Button>
            <Button variant="secondary" disabled>Disabled</Button>
            <Button variant="ghost" disabled>Disabled</Button>
          </div>
        </SubSection>
      </DemoCard>
    </div>
  )
}

// ── Input Gallery ──────────────────────────────────────────────────────────────

function InputGallery() {
  const [showPassword, setShowPassword] = useState(false)

  return (
    <div>
      <SectionTitle>Input</SectionTitle>
      <DemoCard>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <Input label="Email" placeholder="you@example.com" type="email" />
          <Input label="With description" placeholder="Type here..." description="This is helper text." />
          <Input label="Error state" placeholder="Invalid input" error="This field is required." />
          <Input
            label="With prefix"
            placeholder="Search..."
            prefix={<Search size={14} />}
          />
          <Input
            label="With suffix"
            type={showPassword ? 'text' : 'password'}
            placeholder="Password"
            suffix={
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="pointer-events-auto cursor-pointer text-content-tertiary hover:text-content-secondary"
              >
                {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            }
          />
          <Input label="Disabled" placeholder="Cannot edit" disabled />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Textarea Gallery ───────────────────────────────────────────────────────────

function TextareaGallery() {
  const [text, setText] = useState('')

  return (
    <div>
      <SectionTitle>Textarea</SectionTitle>
      <DemoCard>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <Textarea label="Description" placeholder="Tell us more..." rows={3} />
          <Textarea
            label="With character count"
            placeholder="Max 200 characters..."
            showCount
            maxLength={200}
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
          />
          <Textarea label="Error state" error="Please provide more detail." rows={3} />
          <Textarea label="Disabled" placeholder="Cannot edit" disabled rows={3} />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Select Gallery ─────────────────────────────────────────────────────────────

function SelectGallery() {
  const [val, setVal] = useState('option-1')

  return (
    <div>
      <SectionTitle>Select</SectionTitle>
      <DemoCard>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          <Select
            label="With items prop"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            items={[
              { value: 'option-1', label: 'Option 1' },
              { value: 'option-2', label: 'Option 2' },
              { value: 'option-3', label: 'Option 3' },
            ]}
          />
          <Select label="With description" description="Pick your favorite." items={[
            { value: 'react', label: 'React' },
            { value: 'vue', label: 'Vue' },
            { value: 'svelte', label: 'Svelte' },
          ]} />
          <Select label="Error state" error="Selection is required." items={[
            { value: '', label: '-- Select --' },
            { value: 'a', label: 'Alpha' },
          ]} />
          <Select label="Disabled" disabled items={[
            { value: 'locked', label: 'Locked option' },
          ]} />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Checkbox Gallery ───────────────────────────────────────────────────────────

function CheckboxGallery() {
  const [checks, setChecks] = useState({ a: true, b: false, c: false })

  return (
    <div>
      <SectionTitle>Checkbox</SectionTitle>
      <DemoCard>
        <div className="space-y-3">
          <Checkbox
            label="Accept terms"
            description="You agree to our Terms of Service and Privacy Policy."
            checked={checks.a}
            onChange={(v) => setChecks((p) => ({ ...p, a: v }))}
          />
          <Checkbox
            label="Enable notifications"
            checked={checks.b}
            onChange={(v) => setChecks((p) => ({ ...p, b: v }))}
          />
          <Checkbox
            label="Subscribe to updates"
            checked={checks.c}
            onChange={(v) => setChecks((p) => ({ ...p, c: v }))}
          />
          <Checkbox label="Disabled unchecked" disabled />
          <Checkbox label="Disabled checked" checked disabled />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Toggle Gallery ─────────────────────────────────────────────────────────────

function ToggleGallery() {
  const [on1, setOn1] = useState(true)
  const [on2, setOn2] = useState(false)

  return (
    <div>
      <SectionTitle>Toggle</SectionTitle>
      <DemoCard>
        <div className="space-y-3">
          <Toggle label="Dark mode" checked={on1} onChange={setOn1} />
          <Toggle label="Notifications" checked={on2} onChange={setOn2} />
          <Toggle label="Small toggle" size="sm" checked onChange={() => {}} />
          <Toggle label="Disabled" disabled />
          <Toggle label="Disabled on" checked disabled />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Radio Gallery ──────────────────────────────────────────────────────────────

function RadioGallery() {
  const [val, setVal] = useState('cloud-first')

  return (
    <div>
      <SectionTitle>RadioGroup</SectionTitle>
      <DemoCard>
        <RadioGroup
          name="routing"
          value={val}
          onChange={setVal}
          options={[
            { value: 'local-only', label: 'Local only', description: 'Only use local inference.' },
            { value: 'local-first', label: 'Local first', description: 'Prefer local, fall back to cloud.' },
            { value: 'cloud-first', label: 'Cloud first', description: 'Prefer cloud providers.' },
            { value: 'cloud-only', label: 'Cloud only', description: 'Only use cloud providers.' },
          ]}
        />
      </DemoCard>
    </div>
  )
}

// ── Slider Gallery ─────────────────────────────────────────────────────────────

function SliderGallery() {
  const [v1, setV1] = useState(50)
  const [v2, setV2] = useState(0.7)

  return (
    <div>
      <SectionTitle>Slider</SectionTitle>
      <DemoCard>
        <div className="space-y-6 max-w-md">
          <Slider label="Volume" value={v1} onChange={setV1} />
          <Slider label="Temperature" min={0} max={2} step={0.1} value={v2} onChange={setV2} />
          <Slider label="Disabled" value={30} disabled />
        </div>
      </DemoCard>
    </div>
  )
}

// ── Badge Gallery (read-only) ──────────────────────────────────────────────────

function BadgeGallery() {
  return (
    <div>
      <SectionTitle>Badge</SectionTitle>
      <DemoCard>
        <div className="flex flex-wrap gap-2">
          <Badge>neutral</Badge>
          <Badge color="accent">accent</Badge>
          <Badge color="emerald">emerald</Badge>
          <Badge color="amber">amber</Badge>
          <Badge color="red">red</Badge>
          <Badge color="sky">sky</Badge>
          <Badge color="violet">violet</Badge>
          <Badge color="blue">blue</Badge>
          <Badge color="purple">purple</Badge>
        </div>
      </DemoCard>
    </div>
  )
}

// ── Main Gallery ───────────────────────────────────────────────────────────────

export default function ComponentGallery() {
  return (
    <div className="min-h-screen bg-surface-root p-10">
      <h1 className="font-sans text-h1 text-content-primary mb-2">Component Gallery</h1>
      <p className="text-body text-content-secondary mb-12">
        Visual reference for all design system components.
      </p>
      <section className="space-y-12">
        <ButtonGallery />
        <InputGallery />
        <TextareaGallery />
        <SelectGallery />
        <CheckboxGallery />
        <ToggleGallery />
        <RadioGallery />
        <SliderGallery />
        <BadgeGallery />
      </section>
    </div>
  )
}
