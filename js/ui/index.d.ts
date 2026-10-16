import type { ComponentPropsWithoutRef, ReactNode } from "react";

type Div = ComponentPropsWithoutRef<"div">;
export declare function Stack(p: Div): ReactNode;
export declare function Row(p: Div): ReactNode;
export declare function Title(p: ComponentPropsWithoutRef<"h1">): ReactNode;
export declare function Hint(p: ComponentPropsWithoutRef<"p">): ReactNode;
export declare function Card(p: ComponentPropsWithoutRef<"section"> & { title?: ReactNode }): ReactNode;
export declare function Button(p: ComponentPropsWithoutRef<"button"> & { tone?: "plain" | "solid" | "red" | "quiet"; href?: string }): ReactNode;
export declare function Field(p: ComponentPropsWithoutRef<"label"> & { label: ReactNode; hint?: ReactNode; error?: ReactNode }): ReactNode;
export declare function TextInput(p: ComponentPropsWithoutRef<"input">): ReactNode;
export declare function Toggle(p: Omit<ComponentPropsWithoutRef<"input">, "onChange"> & { label?: ReactNode; checked?: boolean; onChange?: (on: boolean) => void }): ReactNode;
export declare function Segmented<V extends string>(p: { options: (V | { value: V; label?: ReactNode })[]; value?: V; onChange?: (v: V) => void; label?: string; className?: string }): ReactNode;
export declare function List(p: ComponentPropsWithoutRef<"ul">): ReactNode;
export declare function ListItem(p: ComponentPropsWithoutRef<"li">): ReactNode;
export declare function KeyCap(p: ComponentPropsWithoutRef<"span"> & { ink: "red" | "yellow" | "black" | "white" }): ReactNode;
export declare function Num(p: ComponentPropsWithoutRef<"span">): ReactNode;
export declare function Notice(p: ComponentPropsWithoutRef<"p"> & { tone?: "bad" }): ReactNode;
